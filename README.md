# repo-mcp

GitHub, GitLab ve Bitbucket üzerindeki repository'leri merkezi olarak
indeksleyen ve elde edilen kod graph'ını MCP üzerinden erişilebilir hale
getiren bir servis.

Sürüm 0.3.0 · [English](README.en.md) · [Değişiklikler](CHANGELOG.md)

## Genel bakış

Bir GitHub organizasyonu, GitLab grubu veya Bitbucket workspace'i connector
olarak tanımlandığında kapsam içindeki repository'ler keşfedilir, klonlanır ve
indekslenir. İndeksleme işini gömülü bir engine yapar; sonuç, proje başına bir
graph dosyası olarak diskte tutulur.

Bu graph'a erişim MCP (Model Context Protocol) üzerinden, HTTP üzerinde
JSON-RPC ile sağlanır. Coding agent'lar, şirket içi chatbot'lar ve CI
pipeline'ları aynı endpoint'e bağlanır. Erişim OIDC token'ı ile doğrulanır,
LDAP grup üyeliğine göre role ve takıma çevrilir.

Sistem iki servisten ve bir veritabanından oluşur. Gateway kimlik doğrulama,
yetkilendirme ve MCP yüzeyinden sorumludur. Indexer repository'leri keşfeder
ve graph'ları günceller. PostgreSQL, çalışma zamanında değiştirilebilen
yapılandırmayı tutar.

## Kullanım örnekleri

MCP istemcisi üzerinden sorulabilecek sorular, engine'in sunduğu tool'lara
karşılık gelir:

- Bir sembolü çağıran veya ona bağlı olan yerleri bulmak: `search_graph`,
  `trace_path`
- Bir projenin genel yapısını çıkarmak: `get_architecture`,
  `get_graph_schema`
- Graph üzerinde doğrudan sorgu çalıştırmak: `query_graph`
- Kaynak kodun ilgili parçasını okumak: `get_code_snippet`, `search_code`
- Bir değişikliğin etkilediği sembolleri hesaplamak: `detect_changes`

Bunlara ek olarak gateway iki composite tool sunar. `explain_change_impact`
önce `detect_changes` ile etki kümesini hesaplar, sonucu bir LLM'e özetletir.
`ask_codebase` doğal dildeki bir soru için `get_architecture` ve
`search_graph` çıktısını toplar ve cevabı bu kanıta dayanarak üretir. Her iki
tool da önce graph sorgusu çalıştırır; modelden graph'ı tahmin etmesi
istenmez.

## Neden

Kod indeksleme araçları genellikle tek geliştiricinin makinesinde çalışacak
şekilde tasarlanır. Bu, birden fazla takımın aynı repository'ler üzerinde
çalıştığı bir ortamda üç sorun çıkarır:

- Aynı repository birden fazla makinede yeniden indekslenir.
- Bir takımın çıkardığı graph başka bir takım tarafından kullanılamaz, bu
  yüzden servisler arası ilişkiler sorgulanamaz.
- İndeksleme sonucuna CI job'ından veya bir chatbot'tan erişilemez, çünkü
  veri geliştiricinin diskindedir.

repo-mcp indekslemeyi merkezi bir servise taşır ve elde edilen graph'a erişimi
takım ve rol bazında sınırlar.

## Nasıl çalışır

1. Indexer, tanımlı connector'ları kullanarak provider API'sinden repository
   listesini çeker. `include` ve `exclude` glob pattern'leri ile bu liste
   filtrelenir.
2. Eşleşen her repository `--filter=blob:none` ile klonlanır ve engine'in CLI
   arayüzü çağrılarak indekslenir. Graph, takım ve proje adına göre ayrılmış
   bir dizine yazılır.
3. Gateway'e gelen bir MCP isteğinde token doğrulanır, token'daki grup
   iddiasından rol ve takım belirlenir, istenen tool ve proje bu yetkilere
   karşı kontrol edilir.
4. Kontrolü geçen çağrı, o takım için ayağa kaldırılmış engine process'ine
   stdio üzerinden iletilir. Process bir süre boşta kalırsa kapatılır.
5. Repository'de değişiklik olduğunda webhook, zamanlanmış tarama veya CI
   tetikleyicisi ile yeniden indeksleme kuyruğa alınır.

## Temel özellikler

**Repository keşfi.** Her connector bir GitHub organizasyonu, bir GitLab grubu
veya bir Bitbucket workspace'ini kapsar. GitLab tarafında alt gruplar
özyinelemeli olarak taranır, Bitbucket tarafında `project_key` ile tek bir
projeye daraltılabilir. Yeni açılan bir repository sonraki taramada
yapılandırma değiştirilmeden devreye girer.

**Üç indeksleme modu.** `full` her şeyi indeksler. `moderate` dosyaları
filtreler ancak benzerlik ve semantik kenarları korur. `fast` bu kenarları
üretmez ve daha hızlı biter. Mod connector başına ayarlanır.

**Yetkilendirmenin üç bağımsız katmanı.** Gateway'de rol yetenekleri ve proje
allowlist'i kontrol edilir. Engine, takıma atanmış tool profiline göre
başlatılır ve profilde olmayan tool'u kabul etmez. Dosya sisteminde her takımın
graph'ı ayrı bir kök dizinde tutulur. Bir katmandaki hata diğerlerini açmaz.

**Çalışma zamanında değiştirilebilen yapılandırma.** Takımlar, roller,
connector'lar, ayarlar ve şifrelenmiş provider token'ları PostgreSQL'de
tutulur. Admin API üzerinden yapılan her değişiklik bir generation sayacını
artırır; servisler bu sayacı belirli aralıklarla kontrol eder ve değiştiyse
yapılandırmayı yeniden okur. Restart gerekmez.

**Web arayüzü.** `/ui` adresinde; graph'ı 3D gezmek ve sistemi yönetmek için.
Motorun kendi arayüzü alınıp bu platforma bağlandı: kimlik sağlayıcı üzerinden
giriş yapar ve codebase hakkındaki her sorusunu `/mcp` üzerinden sorar.

**İki yönetim yüzeyi, tek davranış.** `repo-mcp-admin` komutu ile web
arayüzündeki konsol aynı işlemleri aynı fonksiyonlar üzerinden yapar. Hangisini
kullandığınız fark etmez; ikisi de aynı doğrulamadan geçer ve aynı audit
kaydını üretir.

**Audit kaydı.** Her tool çağrısı için stdout'a tek satır JSON yazılır;
reddedilen çağrılar da dahildir. Yapılandırma değişiklikleri ayrıca
veritabanındaki audit tablosuna kaydedilir ve `/admin/audit` ile okunabilir.

**Prometheus metrikleri.** Her iki servis `/metrics` endpoint'i sunar. Gateway
tarafında MCP istek sayıları, tool çağrı süreleri, canlı engine process sayısı
ve LLM çağrı sonuçları; indexer tarafında kuyruk derinliği, indeksleme
süreleri, keşif ve webhook sonuçları yayınlanır.

## Mimari

```
 Coding agent · Chatbot · CI ──MCP / HTTP + OIDC──▶ Gateway ──▶ engine
              Tarayıcı (/ui) ──MCP / HTTP + OIDC──▶    │        (takım başına
                                                       │         bir process)
                                                       └──HTTPS──▶ LiteLLM ──▶ model

 GitHub · GitLab · Bitbucket ──webhook / zamanlama / CI──▶ Indexer ──▶ graph
```

Gateway ve indexer aynı graph dizinini paylaşır: indexer yazar, gateway okur.
Bu paylaşım nedeniyle ikisi de aynı engine sürümünü çalıştırmak zorundadır.

Ayrıntılı açıklama [docs/architecture.md](docs/architecture.md) içinde.

## Sistem gereksinimleri

**İşletim sistemi ve mimari.** Servisler Linux üzerinde çalışacak şekilde
paketlenmiştir. Engine binary'si `linux/amd64` ve `linux/arm64` için
indirilir; image'da statik olarak derlenmiş sürüm kullanılır, bu yüzden temel
image'ın glibc sürümüne bağımlılık yoktur. macOS üzerinde geliştirme için
`make dev` kullanılabilir, ancak engine binary'sinin ayrıca kurulması gerekir.

**Docker ile çalıştırmak için.** Docker Engine 24 veya üzeri ve Compose v2.
Stack aşağıdaki container'ları başlatır:

| Servis | Image | Port |
| --- | --- | --- |
| gateway | bu repository'den derlenir | 8080 |
| indexer | bu repository'den derlenir | 8082 |
| postgres | `postgres:16-alpine` | 5432 |
| keycloak | `quay.io/keycloak/keycloak:26.0` | 8081 |
| litellm | `ghcr.io/berriai/litellm:main-stable` | 4000 |
| ollama | `ollama/ollama:latest` | 11434 |
| headroom | `ghcr.io/chopratejas/headroom` | 8787 |

Son dördü isteğe bağlıdır ve Compose profili olarak tanımlıdır. Hangilerinin
çalışacağı `deploy/.env` içindeki `COMPOSE_PROFILES` satırı ile belirlenir;
`make setup` bu satırı birkaç soruyla yazar. Profil kapalıyken o servisin
image'ı indirilmez ve container'ı başlatılmaz.

Yalnızca postgres, init, gateway ve indexer ile çalışan bir kurulum
mümkündür. Bu durumda kimlik doğrulama için kendi OIDC sağlayıcısı, composite
tool'lar için kendi LiteLLM proxy'si kullanılır.

**Bellek.** Compose stack'inde gateway için 4 GB, indexer için 8 GB, Ollama
için 16 GB üst sınır tanımlıdır. Bu değerler `GATEWAY_MEMORY_LIMIT`,
`INDEXER_MEMORY_LIMIT` ve `OLLAMA_MEMORY_LIMIT` ile değiştirilebilir.
İndeksleme bellek yoğun bir iştir ve `indexer.concurrency` artırıldığında
indexer'ın üst sınırının da artırılması gerekir.

**Disk.** İki dizin gerekir: klonlanan repository'ler ve üretilen graph'lar.
Repository'ler `--filter=blob:none` ile klonlandığı için tam klondan belirgin
şekilde küçüktür. Helm chart'ının varsayılanları graph'lar için 100 GB,
repository'ler için 200 GB'dir; gerçek ihtiyaç indekslenen kod miktarına göre
değişir.

Graph dosyaları WAL modunda SQLite kullanır. Bu dizin yerel diskte veya block
storage üzerinde tutulmalıdır. NFS üzerinde WAL kilitleme güvenilir
çalışmadığından dosyalar bozulabilir.

**Veritabanı.** PostgreSQL 16 ile test edilmiştir. Compose stack'i bir
PostgreSQL container'ı içerir; `DATABASE_URL` ile harici bir örneğe
yönlendirmek de mümkündür. SQLite yalnızca tek makinede geliştirme ve testler
için desteklenir.

**Kaynak koddan çalıştırmak için.** Python 3.11 veya üzeri, `git`, ve engine
binary'sinin `PATH` üzerinde bulunması gerekir. Engine olmadan sistem ayağa
kalkar ancak tool çağrıları açık bir hata mesajı ile başarısız olur.

**Kubernetes için.** Chart bir veritabanı çalıştırmaz; mevcut bir PostgreSQL
örneği gerekir. Varsayılan kaynak talepleri gateway için 200m CPU / 512 MB,
indexer için 500m CPU / 2 GB'dir. Gateway'in birden fazla replica ile
çalışması için graph volume'ünün `ReadWriteMany` olması gerekir; chart bu
koşul sağlanmadan autoscaling tanımını render etmez.

**Dış erişim.** Indexer'ın provider API'lerine (GitHub, GitLab, Bitbucket) ve
klonlama için git protokolüne erişmesi gerekir. Gateway'in OIDC issuer'ına ve
LiteLLM proxy'sine erişmesi gerekir. Image derlenirken engine binary'si
indirildiğinden, kapalı ağlarda `CBM_RELEASE_BASE` veya `CBM_DOWNLOAD_URL` ile
dahili bir mirror kullanılabilir.

## Kurulum

Üç kurulum biçimi vardır.

### Docker Compose

En hızlı yol.

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp

make setup      # virtualenv'ler, bağımlılıklar, örnek config dosyaları
```

`make setup` sırasında hangi bileşenlerin çalışacağı sorulur:

```
PostgreSQL          bundled | external
Identity            keycloak | external | dev
Model backend       bundled | external | none
Prompt compression  off | on
Repository provider github | gitlab | bitbucket | none
```

Cevaplar `deploy/.env` dosyasına `COMPOSE_PROFILES` satırı olarak yazılır.
Compose bu değişkeni kendisi okur, bu yüzden `make up` ek bir parametre
istemez. Seçim sonradan `make wizard` ile veya bu satırı elle düzenleyerek
değiştirilebilir.

Terminal yoksa — bir pipeline veya script içinde — soru sorulmaz ve tüm
bileşenleri içeren varsayılan kurulum yazılır. Aynı seçimler komut satırından
da verilebilir:

```bash
scripts/wizard.sh --force \
  --identity external --models external --provider github
```

Postgres, init, gateway ve indexer her durumda çalışır. Keycloak, LiteLLM,
Ollama ve headroom seçime bağlıdır; kendi OIDC sağlayıcısı ve kendi LiteLLM
proxy'si olan bir kurulumda dördü de kapatılabilir.

Ardından `deploy/.env` içine bir provider token'ı ve `deploy/scan.yaml` içine
kendi organizasyonunu gösteren bir connector girilir:

```bash
make up         # stack'i başlatır
make smoke      # çalışan stack'e karşı uçtan uca kontrol
```

Stack ilk açılışta veritabanı şemasını oluşturur ve ilk admin hesabını
yaratır. `deploy/.env` içinde `ADMIN_PASSWORD` boş bırakılırsa parola üretilir
ve `init` container'ının log'una bir kez yazılır.

`deploy/.env` ve `deploy/scan.yaml` `.gitignore` içindedir; karşılıkları olan
`deploy/.env.example` ve `deploy/scan.example.yaml` izlenen dosyalardır.

### Kaynak koddan, Docker olmadan

Geliştirme ve inceleme için.

```bash
make setup
make dev
```

`make dev` `.dev/` altında SQLite tabanlı bir veritabanı oluşturur,
`deploy/tenants.yaml` ve `deploy/scan.yaml` dosyalarından seed eder, JWT
doğrulamasını kapatıp statik bir token kabul eder ve iki servisi auto-reload
ile başlatır. Bu mod yalnızca geliştirme içindir.

### Kubernetes

```bash
cp deploy/helm/values-production.example.yaml values-production.yaml
# database.url, image.tag ve secret referansları düzenlenir

helm upgrade --install repo-mcp deploy/helm/repo-mcp \
  -n repo-mcp --create-namespace -f values-production.yaml
```

Chart bir veritabanı çalıştırmaz. Şema migration'ı üretimde otomatik
uygulanmaz; ayrı bir adım olarak çalıştırılır. Ortam ayrımı ve sürüm terfi
akışı [docs/environments.md](docs/environments.md) içinde anlatılmıştır.

Kurulumla ilgili bir şey çalışmazsa `make debug` toolchain'i, engine'i,
yapılandırmayı, depolamayı, iki servisi, canlı bir MCP çağrısını ve model
tarafını sırayla kontrol eder ve ilk hatada durmadan bulduklarını raporlar.

## Yapılandırma

Yapılandırma iki gruba ayrılır.

Veritabanı okunmadan önce bilinmesi gerekenler environment'ta kalır:

| Değişken | Anlamı |
| --- | --- |
| `DATABASE_URL` | PostgreSQL bağlantı adresi |
| `SECRETS_KEY` | Provider token'larını şifreleyen Fernet anahtarı |
| `ENVIRONMENT` | Ortam etiketi; `/readyz` çıktısında görünür |
| `MIGRATE_ON_START` | Başlayan process'in şema migration'ı uygulayıp uygulamayacağı |
| `CBM_BINARY`, `CBM_CACHE_ROOT`, `CBM_REPO_ROOT` | Engine yolu ve depolama dizinleri |
| `CI_TRIGGER_TOKEN` | `/rescan` ve `/trigger` için bearer token |
| `WEBHOOK_SECRET_GITHUB`, `WEBHOOK_SECRET_GITLAB`, `WEBHOOK_SECRET_BITBUCKET` | Webhook imza doğrulaması |

`SECRETS_KEY` tanımlı değilse servisler hazır duruma geçmez; `/readyz` 503
döner ve eksik değişkenin adını bildirir. `/healthz` cevap vermeye devam eder.

Geri kalan ayarlar veritabanında tutulur; web arayüzündeki konsoldan veya
`repo-mcp-admin` ile değiştirilir. Bazıları:

| Anahtar | Varsayılan |
| --- | --- |
| `oidc.issuer`, `oidc.audience`, `oidc.groups_claim` | boş, `repo-mcp`, `groups` |
| `oidc.browser_client_id`, `oidc.browser_scopes` | boş, `openid profile` |
| `litellm.base_url`, `litellm.model` | boş, `gpt-4o-mini` |
| `smart_tools.enabled` | `true` |
| `engine.idle_timeout_seconds`, `engine.call_timeout_seconds` | `900`, `120` |
| `indexer.concurrency`, `indexer.rescan_interval_seconds` | `2`, `86400` |
| `answer_cache.enabled` | `false` |
| `headroom.enabled` | `false` |

Bilinen anahtarların tamamı `common/repo_mcp_common/store.py` içindeki
`DEFAULT_SETTINGS` sözlüğündedir. Listede olmayan bir anahtar admin API
tarafından reddedilir.

Takım ve connector tanımları `repo-mcp-admin import` ile YAML dosyalarından
aktarılabilir. Aşağıdaki iki format hem bu komutun hem admin API'nin kabul
ettiği şekildir.

Roller ve takımlar:

```yaml
roles:
  admin:     [platform-admins]
  lead:      [squad-payments-leads]
  developer: [squad-payments]
  qa:        [chapter-test]
  devops:    [chapter-devops]
  viewer:    [contractors]

tenants:
  payments:
    ldap_groups: [squad-payments, squad-payments-leads, chapter-test]
    tool_profile: analysis
    projects: ["acme-payments-*", "acme-ledger"]
    # İsteğe bağlı: bu takıma ait LiteLLM virtual key'i tutan secret adı
    litellm_key_env: LITELLM_KEY_PAYMENTS
```

`roles` bir LDAP grubunu bir role, `tenants` ise bir LDAP grubunu bir takıma
bağlar. İki eksen bağımsızdır: `chapter-test` grubundaki bir kullanıcı qa
rolüyle, ancak payments takımının verisi üzerinde çalışır. Bir kullanıcı
birden fazla role eşleşirse en yetkili rol seçilir; sıralama
`gateway/app/roles.py` içindeki `ROLE_PRECEDENCE` ile belirlenir.

`tool_profile` iki değer alır. `analysis` inceleme amaçlı, salt okuma yapan
bir yüzey sunar. `scout` daha dar bir tool kümesi içerir. Profil engine
process'ine başlatma parametresi olarak geçirilir; profilde olmayan bir tool
gateway'i aşsa bile engine tarafından reddedilir.

## Connector ayarları

Connector'lar hangi repository'lerin indeksleneceğini belirler:

```yaml
connectors:
  - name: acme-github
    type: github
    org: acme
    token_env: GITHUB_TOKEN
    tenant: payments
    include: ["payments-*", "ledger"]
    exclude: ["*-archive"]
    mode: moderate
    persistence: true

  - name: acme-gitlab
    type: gitlab
    group: acme/backend            # alt gruplar özyinelemeli taranır
    base_url: https://gitlab.example.com
    token_env: GITLAB_TOKEN
    tenant: checkout
    mode: moderate

  - name: acme-bitbucket
    type: bitbucket
    workspace: acme
    project_key: PAY               # isteğe bağlı, tek projeye daraltır
    username: ci-bot
    token_env: BITBUCKET_APP_PASSWORD
    tenant: payments
    mode: fast
```

`base_url` self-hosted GitHub Enterprise, GitLab ve Bitbucket Server
kurulumları için kullanılır. `token_env` bir environment değişkeninin adıdır;
token değeri bu dosyaya yazılmaz. Admin API üzerinden tanımlanan
connector'larda token şifrelenmiş olarak veritabanında saklanır.

`persistence: true` olduğunda engine `.codebase-memory/graph.db.zst` dosyasını
üretir; geliştirici makineleri bu dosyadan başlayarak sıfırdan indekslemek
zorunda kalmaz.

## Web arayüzü

Gateway `/ui` adresinde bir tarayıcı arayüzü sunar. Dört sekme: projeler,
graph'ın 3D haritası, doğal dille soru sorma ve yönetim konsolu.

![Graph](docs/images/ui-graph.png)

Bu arayüz sıfırdan yazılmadı — motorun kendi arayüzü (`graph-ui`, MIT,
React + Three.js) alınıp bu platforma bağlandı. Gerekçesi
[docs/adr/0011-adopt-the-upstream-interface.md](docs/adr/0011-adopt-the-upstream-interface.md)
içinde; neyin neden değiştiğini
[gateway/webui/README.md](gateway/webui/README.md) anlatıyor.

Değişen tek temel şey transport oldu. Upstream motorun loopback sunucusuna
`POST /rpc` ile konuşuyordu; artık `POST /mcp` ile konuşuyor — aynı JSON-RPC
protokolü, aynı tool isimleri, ama gateway üzerinden. Yani her çağrı
kullanıcının token'ını ve takımını taşıyor; rol yetkileri, proje allowlist'i
ve motor tool profili kontrol ediliyor. Arayüzün ayrı bir okuma yolu yok.

Upstream'in tek makineye özel yüzeyleri (dosya sistemi gezme, process ve log
görüntüleme) kaldırıldı; yerine yönetim konsolu geldi. Diğer HTTP uçları
tool çağrılarına bağlandı: proje sağlığı ve indeks durumu `index_status`,
ADR'ler `manage_adr`, indeksleme `index_repository`, silme `delete_project`.
Böylece hepsi bir yetkinin arkasında.

**3D yerleşim.** MCP'de karşılığı olmayan tek şey bu: motor yerleşimi C
tarafında hesaplayıp bir loopback portunda sunuyor. Gateway isteği tıpkı bir
tool çağrısı gibi yetkilendiriyor — token, takım, `READ_GRAPH` yetkisi, proje
allowlist'i — ve ancak ondan sonra o porta proxy yapıyor. 860 satırlık C
kodunu Python'da yeniden yazmak hem yavaş olurdu hem de zamanla sapardı.

O portun kendi kimlik doğrulaması yok; bu yüzden `127.0.0.1`'e bağlanıyor,
portu gateway seçiyor ve hiçbir zaman dışarı açılmıyor. Güven sınırı stdio
borusununkiyle aynı.

**Soru sorma.** `ask_codebase` önce `get_architecture` ve `search_graph`
çalıştırır, cevabı yalnızca dönen kanıta dayandırır ve andığı her sembolün
qualified name'ini gösterir. Modelden graph'ı tahmin etmesi istenmez; bu yüzden
cevap denetlenebilir. Model backend'i yoksa sayfa hangi ayarın açılması
gerektiğini söyler.

![Soru sorma](docs/images/ui-ask.png)

**Reddedilme.** Platformun kesinlikle reddedeceği bir kontrol gizlenmez;
gerekçesi üzerinde yazılı olarak devre dışı gösterilir — yetki hatası arayan
bir yöneticinin bakacak bir şeyi olmalı. Gelen reddi de platformun kendi
cümlesiyle gösterilir: `'manage_adr' is not available in this session (role:
lead, squad: payments)`. Hiçbir şey sessizce başarısız olmaz.

**Giriş.** `oidc.issuer` ve `oidc.browser_client_id` ayarlıysa PKCE ile
Authorization Code akışı çalışır; tarayıcı public client'tır, client secret
yoktur. Browser client tanımlı değilse token kutusu kalır, geliştirme modunda
ekran token'ların doğrulanmadığını açıkça yazar. Token'lar yalnızca
`sessionStorage`'da tutulur.

Arayüz kaynağı `gateway/webui/` altında, Vite ile derleniyor; derleme çıktısı
repoya konmuyor. Çalışma anında CDN'den bir şey çekilmiyor, dolayısıyla
internet erişimi olmayan bir kurulumda çalışır — ama internet erişimi olmayan
bir *derleme* için npm aynası gerekir. Bu, seçimin bilinçli bedeli.

Ayrıntılar [docs/web-interface.md](docs/web-interface.md) içinde.

## MCP istemci bağlantısı

Gateway tek bir endpoint sunar: `POST /mcp`. Protokol HTTP üzerinde JSON-RPC
2.0'dır ve `initialize`, `tools/list`, `tools/call`, `ping` metotları
desteklenir.

```bash
curl -s http://localhost:8080/mcp \
  -H "Authorization: Bearer $OIDC_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

`tools/list` çıktısı çağıran kullanıcıya göre değişir: rolün yetkisi olmayan
ve takımın tool profilinde bulunmayan tool'lar listeye girmez.

Bir kullanıcı birden fazla takıma üyeyse istekte `X-Tenant` header'ı ile
takım seçilmelidir. Header verilmezse gateway hangi takımların uygun olduğunu
bildiren bir hata döner.

## Kimlik doğrulama ve yetkilendirme

Gateway kendi kullanıcı tablosunu tutmaz. Token doğrulaması OIDC issuer'ının
JWKS endpoint'inden alınan anahtarlarla yapılır; `oidc.audience` ve
`oidc.groups_claim` ayarları hangi audience'ın kabul edileceğini ve grup
listesinin hangi claim'de aranacağını belirler. LDAP veya Active Directory
grupları Keycloak üzerinden bu claim'e taşınır.

Roller ve yetkileri `gateway/app/roles.py` içinde tanımlıdır:

| Rol | Yetkiler |
| --- | --- |
| `admin` | tümü |
| `lead` | developer yetkileri, ek olarak indeksleme tetikleme ve ADR yönetimi |
| `developer` | graph okuma, kaynak okuma, ham sorgu, değişiklik analizi, composite tool'lar |
| `qa` | developer ile aynı |
| `devops` | graph okuma, ham sorgu, değişiklik analizi, indeksleme tetikleme, trace ingest, composite tool'lar; kaynak okuma yoktur |
| `viewer` | yalnızca graph okuma |

Bu rollerin yanında, yalnızca admin API'ye erişebilen yerel bir admin hesabı
bulunur. Bu hesap ilk açılışta oluşturulur ve OIDC yapılandırılmadan önce
sistemi yönetilebilir kılmak içindir. MCP tool'larını çağıramaz, graph
okuyamaz, kaynak kod göremez. Gerekçesi
[docs/adr/0007-break-glass-administrator.md](docs/adr/0007-break-glass-administrator.md)
içinde.

## Yönetim

Takımlar, roller, connector'lar, secret'lar, ayarlar, audit kaydı ve answer
cache iki yerden yönetilir: `repo-mcp-admin` komutu ve web arayüzündeki
yönetim konsolu.

İkisi aynı işlemlerdir. Her ikisi de `common/repo_mcp_common/admin.py`
içindeki aynı fonksiyonları çağırır; terminalden oluşturulan bir takım ile
tarayıcıdan oluşturulan aynı satırdır, aynı kurallarla doğrulanır ve aynı
audit tablosuna yazılır. Aralarında bir fark oluşursa
`common/tests/test_cli_config.py` bunu yakalar.

```bash
repo-mcp-admin squad set payments \
  --group squad-payments --project 'acme-payments-*' --profile analysis
repo-mcp-admin role set lead --group squad-payments-leads
repo-mcp-admin connector set acme-github \
  --provider github --squad payments --setting org=acme \
  --token-secret connector.acme-github.token
repo-mcp-admin settings
repo-mcp-admin audit --limit 25
```

![Yönetim konsolu](docs/images/ui-admin.png)

Hiçbir değişiklik restart gerektirmez: her yazma bir generation sayacını
artırır, iki servis de bu sayacı belirli aralıklarla kontrol eder. Terminalden
yapılan bir değişiklik de çalışan gateway'e bu yolla ulaşır.

Komutların tam listesi ve her birinin ne yaptığı
[docs/administration.md](docs/administration.md) içinde.

## Webhook ve yeniden indeksleme

Graph dört yoldan güncellenir.

**Webhook.** `POST /webhook/{provider}` endpoint'i `github`, `gitlab` ve
`bitbucket` değerlerini kabul eder. İmza `WEBHOOK_SECRET_<PROVIDER>`
değişkenindeki secret ile doğrulanır; secret tanımlı değilse endpoint 503
döner. GitHub için `X-Hub-Signature-256`, GitLab için `X-Gitlab-Token`
kullanılır. Branch silme olayları indekslemeyi tetiklemez.

**Zamanlanmış tarama.** Indexer, `indexer.rescan_interval_seconds` ayarında
belirtilen aralıkla connector'ları yeniden tarar ve bulunan tüm
repository'leri kuyruğa alır.

**CI tetikleyicisi.** `POST /trigger` gövdesinde `repository` ve isteğe bağlı
`sha` alanları ile tek bir repository'yi belirli bir commit'te indeksler.
`POST /rescan` tüm connector'ları yeniden tarar. Her ikisi de
`CI_TRIGGER_TOKEN` ile bearer authentication ister.

**Elle.** `index_repository` tool'u, bu yetkiye sahip rollerle çağrılabilir.

Kuyruk proje bazında serileştirilir: aynı projeye ait ikinci bir iş, ilki
bitene kadar başlamaz. Kısa aralıkla gelen birden fazla push tek bir işe
indirgenir.

## LLM yapılandırması

Composite tool'lar LiteLLM proxy'si üzerinden çalışır. `litellm.base_url` ve
`litellm.model` ayarları hangi proxy'nin ve hangi modelin kullanılacağını
belirler. Model seçimi tamamen proxy tarafında yapılır; hosted bir servis,
vLLM veya Ollama arasındaki fark repo-mcp tarafında bir kod değişikliği
gerektirmez.

Her takım kendi LiteLLM virtual key'ini kullanabilir. Bu durumda bütçe, rate
limit ve prompt log'ları LiteLLM tarafında takım bazında ayrışır.

`smart_tools.enabled` ayarı `false` yapıldığında composite tool'lar listeden
kalkar ve çağrıldıklarında reddedilir. Engine'in kendi tool'ları bundan
etkilenmez.

İki isteğe bağlı bileşen daha vardır, ikisi de varsayılan olarak kapalıdır:

- **Answer cache.** `ask_codebase` cevaplarını takım, proje ve graph epoch'una
  göre saklar. Aynı sorunun tekrarı LLM çağrısı yapmadan cevaplanır. Bir
  proje yeniden indekslendiğinde epoch artar ve önceki graph'tan üretilmiş
  cevaplar eşleşmeyi bırakır. Embedding modeli tanımlanırsa benzer sorular da
  eşleşebilir. Gerekçesi
  [docs/adr/0009-answer-cache.md](docs/adr/0009-answer-cache.md) içinde.
- **Headroom.** LiteLLM'in önünde çalışan bir prompt sıkıştırma proxy'si.
  Kendi container'ı olarak, sabitlenmiş bir image tag'i ile çalışır.
  Erişilemediğinde gateway doğrudan LiteLLM'e döner. Embedding istekleri bu
  proxy'den geçmez.

## Gözlemlenebilirlik ve audit

`/metrics` endpoint'i her iki serviste Prometheus formatında çıktı verir.
Metrik isimleri `repo_mcp_` öneki ile başlar.

`/healthz` process'in ayakta olduğunu bildirir. `/readyz` yapılandırmanın
okunabildiğini, şemanın mevcut olduğunu ve en az bir admin hesabının
bulunduğunu kontrol eder; gateway ayrıca yüklü takımları ve generation
numarasını döner. Yapılandırma eksikse `/readyz` 503 ve sebebi döner.

Tool çağrıları stdout'a JSON olarak yazılır. Kayıt kullanıcıyı, takımı,
tool'u, projeyi, sonucu ve süreyi içerir; reddedilen çağrılarda ret sebebi de
bulunur. Yapılandırma değişiklikleri veritabanındaki audit tablosuna yazılır.

## Bilinen sınırlamalar

- Web arayüzü yoktur. Sistem MCP endpoint'i, admin API'si ve health
  endpoint'lerinden ibarettir.
- Graph'ın geçmişi tutulmaz. Engine yalnızca güncel graph'ı saklar, bu yüzden
  iki tarih arasındaki farkı sorgulamak mümkün değildir. Tasarımı
  [docs/adr/0004-graph-history.md](docs/adr/0004-graph-history.md) içinde,
  uygulaması yoktur.
- Indexer tek replica çalışmalıdır. Kuyruk ve proje kilitleri process içinde
  tutulduğundan iki replica aynı projeyi aynı anda indeksleyebilir.
- Gateway'in yatay ölçeklenmesi paylaşımlı bir dosya sistemi gerektirir ve
  graph dosyaları SQLite WAL kullandığı için NFS uygun değildir. Helm chart'ı
  `ReadWriteMany` olmadan autoscaling tanımını render etmeyi reddeder.
- Her iki servis de `WEB_CONCURRENCY=1` ile çalışır. Her uvicorn worker'ı
  takım başına ayrı bir engine process'i açacağından bu değer artırılmaz.
- Engine'in embedding modeli binary içinde derlenmiştir ve
  değiştirilemez. LiteLLM yalnızca composite tool'lar ve answer cache için
  kullanılır.
- Provider keşfi, webhook'lar ve LLM katmanı unit testleriyle kaplıdır ancak
  gerçek bir GitHub organizasyonuna, canlı bir LiteLLM proxy'sine veya
  Keycloak kurulumuna karşı henüz çalıştırılmamıştır.
- Container image'ları CI tarafından üretilir; henüz bir registry'ye
  yayınlanmamıştır.

Neyin hangi durumda olduğu [docs/roadmap.md](docs/roadmap.md) ve
[memory-bank/progress.md](memory-bank/progress.md) içinde ayrıntılı olarak
listelenmiştir.

## Geliştirme

```bash
make setup      # virtualenv'ler ve bağımlılıklar
make test       # lint, unit testler, örnek config doğrulaması, shellcheck
make dev        # iki servisi lokalde çalıştırır, Docker gerekmez
make debug      # çalışmayan bileşeni tespit eder
make verify     # test, dokümantasyon kuralları, chart ve sürüm tutarlılığı,
                # secret taraması
make help       # tüm hedefler
```

Her make hedefi [`scripts/`](scripts/) altındaki bir script'i çağırır;
script'ler doğrudan da çalıştırılabilir. Ayrıntı
[docs/development.md](docs/development.md) içinde.

Sürüm numarası [`VERSION`](VERSION) dosyasında tutulur.
`scripts/version.sh --bump patch|minor|major` bu numarayı üç Python paketine
ve Helm chart'ına yayar; `make verify` hepsinin tutarlı olduğunu kontrol eder.

`docs/images/` altındaki görseller `make screenshots` ile çalışan bir
gateway'den yeniden üretilir.

## Katkıda bulunma

Geliştirme `dev` branch'i üzerinden yürür. Branch isimleri
`feature/`, `bugfix/`, `hotfix/`, `chore/` veya `docs/` ön eki ile başlar ve
bu kural CI tarafından kontrol edilir. Kod, test ve dokümantasyon kuralları
[docs/code-standards.md](docs/code-standards.md) içinde; süreç
[CONTRIBUTING.md](CONTRIBUTING.md) içinde tanımlıdır.

Bir değişikliğin tamamlanmış sayılması için `make verify` çıktısının temiz
olması gerekir.

## Güvenlik

Provider token'ları ve LiteLLM anahtarları veritabanında Fernet ile
şifrelenmiş olarak tutulur; anahtar `SECRETS_KEY` environment değişkeninden
gelir. Admin API secret değerlerini geri döndürmez ve audit kaydına yazmaz.

Engine'in kendi kimlik doğrulaması yoktur ve doğrudan dışarıya açılmamalıdır.
Gateway tek giriş noktasıdır.

Güvenlik açığı bildirimi için [SECURITY.md](SECURITY.md) dosyasına bakınız.

## Lisans

MIT — [LICENSE](LICENSE).

repo-mcp üçüncü taraf bir indeksleme engine'i paketler. Lisans bilgisi ve atıf
[NOTICE](NOTICE) dosyasındadır.
