/* The graph view.
 *
 * A real codebase graph is tens of thousands of nodes and edges. Canvas 2D and
 * the SVG-based graph libraries stop being usable somewhere in the low
 * thousands, so this uses Sigma's WebGL renderer with graphology as the data
 * model — one draw call class for all nodes, one for all edges, and the GPU
 * doing the work.
 *
 * Three vendored UMD bundles, all MIT, all served from this origin: no build
 * step and nothing fetched from a CDN, so an air-gapped installation works.
 * See ui/vendor/README.md for versions and how to update them.
 *
 * The layout runs in a Web Worker. A force layout on 20 000 nodes takes
 * seconds of arithmetic; on the main thread that is seconds of dropped frames,
 * however finely it is sliced, because each slice still blocks. In a worker
 * the main thread only draws, so the graph can be panned and zoomed while it
 * is still settling — which is also the part that looks like something
 * happening. graphology-library already ships the worker supervisor, so this
 * costs no extra bundle.
 *
 * The worker is created from a blob URL. A deployment with a content security
 * policy that forbids `worker-src blob:` cannot have one, so there is a
 * main-thread fallback that slices the same layout between frames.
 */

'use strict';

/* The three vendored bundles are UMD and load as classic scripts before the
 * modules, so they arrive as globals. Reading them once here keeps that fact
 * in one place instead of scattered through the file. */
const Graph = window.graphology;
const forceAtlas2 = window.graphologyLibrary.layoutForceAtlas2;
const FA2Layout = window.graphologyLibrary.FA2Layout;

/* Colours per node label. get_graph_schema reports which labels a project
 * actually has; these are the ones the engine emits, and anything it adds
 * later falls through to grey rather than breaking the legend. */
const LABEL_COLOURS = {
  Function: '#4dabf7', Method: '#63e6be', Class: '#b197fc', File: '#ffd43b',
  Module: '#ff922b', Variable: '#f783ac', Folder: '#69db7c', EnvVar: '#ffa8a8',
  Decorator: '#a5d8ff', Section: '#dee2e6', Branch: '#e599f7', Project: '#ff8787',
  Route: '#20c997', Channel: '#fab005',
};
const OTHER = '#868e96';
const colourFor = (label) => LABEL_COLOURS[label] || OTHER;

/* Beyond this the browser is not the problem — the payload is. The graph is
 * fetched as JSON over one request, and a million edges is not a download
 * anybody wants. The cap is reported rather than applied silently. */
const MAX_EDGES = 60000;

export class GraphView {
  constructor(container, { onSelect } = {}) {
    this.container = container;
    this.onSelect = onSelect || (() => {});
    this.graph = new Graph({ multi: true, type: 'directed' });
    this.sigma = null;
    this.worker = null;
    this.frame = null;
    this.stopped = true;
    this.focus = null;
    this.neighbours = null;
    this.hidden = { labels: new Set(), kinds: new Set() };
    this.truncated = false;
    this.counts = { labels: new Map(), kinds: new Map() };
  }

  /* rows are [fromName, fromLabel, kind, toName, toLabel] as query_graph
   * returns them. Building the graphology model here rather than in the API
   * keeps the wire format the engine's own. */
  load(rows) {
    this.stopLayout();
    this.graph.clear();
    this.counts = { labels: new Map(), kinds: new Map() };
    this.truncated = rows.length >= MAX_EDGES;

    const bump = (map, key) => map.set(key, (map.get(key) || 0) + 1);

    const addNode = (name, label) => {
      if (!name) return null;
      if (!this.graph.hasNode(name)) {
        this.graph.addNode(name, {
          label: name,
          nodeLabel: label || 'Other',
          size: 3,
          color: colourFor(label),
          // Start on a circle rather than at random: force layouts converge
          // faster and more evenly from a ring than from a cloud.
          x: Math.cos(this.graph.order) * (100 + this.graph.order % 400),
          y: Math.sin(this.graph.order) * (100 + this.graph.order % 400),
        });
        bump(this.counts.labels, label || 'Other');
      }
      return name;
    };

    for (const [from, fromLabel, kind, to, toLabel] of rows) {
      const a = addNode(from, fromLabel);
      const b = addNode(to, toLabel);
      if (!a || !b) continue;
      this.graph.addEdge(a, b, { kind: kind || 'RELATED', size: 0.6, color: '#3a4048' });
      bump(this.counts.kinds, kind || 'RELATED');
    }

    // Degree drives size, so the things everything points at stand out. Capped
    // so one hub does not swallow the view.
    this.graph.forEachNode((node) => {
      const degree = this.graph.degree(node);
      this.graph.setNodeAttribute(node, 'size', Math.min(2 + Math.sqrt(degree) * 1.6, 18));
      this.graph.setNodeAttribute(node, 'degree', degree);
    });

    this.render();
    return { nodes: this.graph.order, edges: this.graph.size, truncated: this.truncated };
  }

  render() {
    if (this.sigma) this.sigma.kill();
    this.sigma = new window.Sigma(this.graph, this.container, {
      renderEdgeLabels: false,
      defaultEdgeType: 'line',
      labelDensity: 0.2,
      labelGridCellSize: 90,
      labelRenderedSizeThreshold: 7,
      labelColor: { color: getComputedStyle(document.documentElement)
        .getPropertyValue('--text').trim() || '#ddd' },
      // Filtering happens in the reducers rather than by removing nodes, so a
      // filter is instant and reversible and the layout never moves.
      nodeReducer: (node, data) => {
        if (this.hidden.labels.has(data.nodeLabel)) return { ...data, hidden: true };
        if (this.focus && node !== this.focus && !this.neighbours?.has(node)) {
          return { ...data, color: '#39414d', label: '', size: Math.min(data.size, 3) };
        }
        return data;
      },
      edgeReducer: (edge, data) => {
        if (this.hidden.kinds.has(data.kind)) return { ...data, hidden: true };
        const [from, to] = this.graph.extremities(edge);
        if (this.hidden.labels.has(this.graph.getNodeAttribute(from, 'nodeLabel'))
          || this.hidden.labels.has(this.graph.getNodeAttribute(to, 'nodeLabel'))) {
          return { ...data, hidden: true };
        }
        if (this.focus && from !== this.focus && to !== this.focus) {
          return { ...data, hidden: true };
        }
        return data;
      },
    });

    this.sigma.on('clickNode', ({ node }) => this.select(node));
    this.sigma.on('clickStage', () => this.select(null));
  }

  /* Selecting dims everything that is not a neighbour and moves the camera to
   * the node. The camera animation is what makes a jump readable — without it
   * the graph simply looks different afterwards. */
  select(node) {
    this.focus = node;
    this.neighbours = node ? new Set(this.graph.neighbors(node)) : null;
    this.sigma.refresh();

    if (node) {
      this._centreOn(node);
      this.onSelect({
        name: node,
        label: this.graph.getNodeAttribute(node, 'nodeLabel'),
        degree: this.graph.getNodeAttribute(node, 'degree'),
        out: this.graph.outEdges(node).map((e) => ({
          kind: this.graph.getEdgeAttribute(e, 'kind'), to: this.graph.extremities(e)[1],
        })),
        in: this.graph.inEdges(node).map((e) => ({
          kind: this.graph.getEdgeAttribute(e, 'kind'), from: this.graph.extremities(e)[0],
        })),
      });
    } else {
      this.onSelect(null);
    }
  }

  /* Sigma normalises coordinates to the graph's bounding box on every refresh,
   * so while the layout is still spreading the graph out, a camera position is
   * only correct for the frame it was read in. Centring again when the layout
   * finishes is what keeps a node selected mid-layout from drifting off the
   * screen. */
  _centreOn(node) {
    const position = this.sigma?.getNodeDisplayData(node);
    if (!position) return;
    this.sigma.getCamera().animate(
      { x: position.x, y: position.y, ratio: Math.min(this.sigma.getCamera().ratio, 0.25) },
      { duration: 500, easing: 'quadraticInOut' },
    );
  }

  focusByName(name) {
    if (this.graph.hasNode(name)) { this.select(name); return true; }
    // Fall back to a suffix match: search returns qualified names, the graph
    // holds bare ones.
    const match = this.graph.findNode((node) => node === name || node.endsWith(`.${name}`));
    if (match) { this.select(match); return true; }
    return false;
  }

  /* ForceAtlas2. `onTick` reports progress so the interface can say how far
   * along it is instead of appearing to hang.
   *
   * The worker converges on wall-clock time rather than an iteration count:
   * it runs at whatever rate the machine allows, so a time budget is both the
   * honest unit of progress and the thing that keeps a large graph bounded. */
  runLayout(onTick) {
    this.stopLayout();
    const settings = forceAtlas2.inferSettings(this.graph);
    settings.barnesHutOptimize = this.graph.order > 800;
    settings.slowDown = 1 + Math.log10(Math.max(this.graph.order, 10));

    this.stopped = false;
    if (FA2Layout && this._startWorkerLayout(settings, onTick)) return;
    this._startSlicedLayout(settings, onTick);
  }

  _startWorkerLayout(settings, onTick) {
    try {
      this.worker = new FA2Layout(this.graph, { settings });
      this.worker.start();
    } catch (error) {
      // No worker: a content security policy, or a browser without blob
      // workers. Not fatal, and not worth an error in front of anyone.
      this.worker = null;
      return false;
    }

    const budget = this.graph.order > 8000 ? 14000 : this.graph.order > 2000 ? 9000 : 5000;
    const started = performance.now();

    const watch = () => {
      if (this.stopped) return;
      const progress = Math.min(1, (performance.now() - started) / budget);
      // The worker writes positions straight into the graph, which Sigma
      // already listens to; the refresh is here only for the frames where
      // nothing else changed.
      this.sigma?.refresh();
      onTick?.(progress);
      if (progress >= 1) {
        this.stopLayout();
        if (this.focus) this._centreOn(this.focus);
        onTick?.(1);
        return;
      }
      this.frame = requestAnimationFrame(watch);
    };
    this.frame = requestAnimationFrame(watch);
    return true;
  }

  _startSlicedLayout(settings, onTick) {
    // Enough to settle, and bounded so a huge graph still finishes.
    const total = this.graph.order > 8000 ? 220 : this.graph.order > 2000 ? 400 : 600;
    const slice = this.graph.order > 8000 ? 4 : 12;
    let done = 0;

    const step = () => {
      if (this.stopped) return;
      forceAtlas2.assign(this.graph, { iterations: slice, settings });
      done += slice;
      this.sigma?.refresh();
      onTick?.(Math.min(1, done / total));
      if (done < total) {
        this.frame = requestAnimationFrame(step);
      } else {
        this.frame = null;
        if (this.focus) this._centreOn(this.focus);
        onTick?.(1);
      }
    };
    this.frame = requestAnimationFrame(step);
  }

  stopLayout() {
    this.stopped = true;
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = null;
    // kill() terminates the worker; stop() alone leaves it parked in memory,
    // and a page that draws several graphs would accumulate them.
    this.worker?.kill();
    this.worker = null;
  }

  setHidden(kind, value, hidden) {
    const set = kind === 'label' ? this.hidden.labels : this.hidden.kinds;
    if (hidden) set.add(value); else set.delete(value);
    this.sigma?.refresh();
  }

  resetCamera() {
    this.sigma?.getCamera().animate({ x: 0.5, y: 0.5, ratio: 1 },
      { duration: 400, easing: 'quadraticInOut' });
  }

  destroy() {
    this.stopLayout();
    this.sigma?.kill();
    this.sigma = null;
  }
}

GraphView.MAX_EDGES = MAX_EDGES;
GraphView.colourFor = colourFor;

// The map page reaches it through the class, so the module needs no other
// export; keeping the global is what lets index.html load it before the
// modules without a circular import.
window.GraphView = GraphView;
