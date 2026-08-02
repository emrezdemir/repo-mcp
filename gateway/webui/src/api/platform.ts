/* The endpoints upstream's interface used, expressed as tool calls.
 *
 * Upstream this interface talked to a server on the same machine, so it could
 * ask about processes, browse the filesystem and start an index by path.
 * Here the same needs are met by engine tools, which means each one is
 * authorized against the caller's role and their squad's project allowlist.
 *
 * One thing deliberately has no replacement: browsing the filesystem. There is
 * no path a person should be choosing by hand on a shared platform — a
 * repository arrives because a connector discovered it, and the indexer clones
 * it under the squad's own root. See docs/adr/0002-tenancy-model.md.
 */

import { callTool } from "./rpc";

export interface ProjectHealth {
  status: "healthy" | "corrupt" | "missing";
  nodes?: number;
  edges?: number;
  reason?: string;
}

/* Upstream read a project's health off the graph file directly. index_status
 * is the tool that answers the same question, and it goes through the ACL. */
export async function projectHealth(project: string): Promise<ProjectHealth> {
  try {
    const status = await callTool<Record<string, unknown>>("index_status", { project });
    const nodes = Number(status.nodes ?? status.total_nodes ?? 0);
    const edges = Number(status.edges ?? status.total_edges ?? 0);
    if (!nodes) return { status: "missing", reason: "nothing indexed yet" };
    return { status: "healthy", nodes, edges };
  } catch (exception) {
    return { status: "corrupt", reason: (exception as Error).message };
  }
}

export interface Adr {
  has_adr: boolean;
  content?: string;
  updated_at?: string;
}

export async function readAdr(project: string): Promise<Adr> {
  // A refusal is not "there is no ADR" — it is "you may not see one", and the
  // difference matters to whoever is looking. It is left to the caller.
  const result = await callTool<Record<string, unknown>>("manage_adr", {
    project,
    mode: "read",
  });
  const content = (result.content ?? result.adr ?? "") as string;
  return { has_adr: Boolean(content), content, updated_at: result.updated_at as string };
}

export async function writeAdr(project: string, content: string): Promise<void> {
  await callTool("manage_adr", { project, mode: "update", content });
}

export interface ProjectSummary {
  name: string;
  root_path?: string;
  git?: { remote?: string; branch?: string };
}

export async function listProjects(): Promise<ProjectSummary[]> {
  const result = await callTool<{ projects?: ProjectSummary[] }>("list_projects", {});
  return result.projects ?? [];
}

/* Upstream indexed an arbitrary path. Here a repository is indexed where the
 * indexer put it, under the squad's own root, and the gateway refuses any
 * path outside that root regardless of what is asked for. */
export async function indexProject(repoPath: string, projectName?: string): Promise<void> {
  const args: Record<string, unknown> = { repo_path: repoPath };
  if (projectName) args.name = projectName;
  await callTool("index_repository", args);
}

export async function deleteProject(project: string): Promise<void> {
  await callTool("delete_project", { project });
}

/* Git metadata for the "open this on GitHub" links. list_projects already
 * carries it, so there is no second request and no second endpoint. */
export async function repoInfo(project: string): Promise<ProjectSummary["git"] | null> {
  const projects = await listProjects();
  return projects.find((entry) => entry.name === project)?.git ?? null;
}

export interface SearchHit {
  name: string;
  qualified_name: string;
  label: string;
  file_path: string;
  start_line?: number;
  end_line?: number;
  rank?: number;
}

/* Search the whole project, not just what is drawn.
 *
 * The graph is drawn up to a node budget — five thousand by default, out of
 * a codebase that may have fifty. Filtering the drawn nodes therefore answers
 * "no matches" for symbols that plainly exist, which is not a missing feature
 * but a wrong answer. `search_graph` is BM25 over the whole project and is
 * what the question deserves.
 */
export async function searchGraph(
  project: string,
  query: string,
  limit = 50,
): Promise<{ hits: SearchHit[]; total: number; truncated: boolean }> {
  const result = await callTool<{
    results?: SearchHit[];
    total?: number;
    has_more?: boolean;
  }>("search_graph", { project, query, limit });
  return {
    hits: result.results ?? [],
    total: result.total ?? 0,
    truncated: Boolean(result.has_more),
  };
}
