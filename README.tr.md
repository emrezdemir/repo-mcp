# repo-mcp

**Organizasyon geneli merkezi kod zekâsı.** Bir GitHub organizasyonu, GitLab
grubu veya Bitbucket workspace'i verirsiniz; altındaki tüm repolar
sorgulanabilir bir bilgi grafiğine dönüşür — MCP üzerinden kodlama
agent'ları, chatbotlar ve CI pipeline'ları için.

[English](README.md)

---

`repo-mcp`, mükemmel bir yerel kod zekâsı motoru olan
[codebase-memory-mcp][cbm]'yi (CBM) sarmalar ve paylaşımlı bir kurulumun
ihtiyaç duyduğu, CBM'in ise tasarım gereği içermediği parçaları ekler: ağ
transportu, LDAP tabanlı kimlik, squad bazlı kiracılık, rol tabanlı
yetkilendirme, denetim kaydı, otomatik repo keşfi ve [LiteLLM][litellm]
üzerinden geçen bir akıl katmanı.

Motora hiç dokunulmaz. Upstream sürümleri bir versiyon numarası değiştirilerek
alınır — bkz. [ADR-0001](docs/adr/0001-wrap-dont-fork.md).

[cbm]: https://github.com/DeusData/codebase-memory-mcp
[litellm]: https://github.com/BerriAI/litellm

## Neden

CBM bir repoyu bilgi grafiğine indeksler; böylece agent grep yapmak yerine
*"bu fonksiyonu kim çağırıyor?"* diye sorabilir. Hızlı, çevrimdışı ve tasarımı
gereği tek kullanıcılıdır: yalnız stdio, kimlik doğrulama yok, hesap başına tek
cache dizini.

Bu tasarım bir dizüstü için doğru, bir organizasyon için yanlıştır. Her
geliştirici aynı repoları yeniden indeksler, takımlar arasında graph
paylaşılamaz, servisler arası bir soru cevaplanamaz ve aynı bilgi bir chatbot
veya CI işine verilemez.

repo-mcp motoru olduğu gibi bırakıp eksik yarıyı ekler.

## Ne yapar

- **Repoları otomatik keşfeder.** GitHub organizasyonu, GitLab grubu (iç içe
  alt gruplar dahil) veya Bitbucket workspace'i başına bir konnektör, glob
  desenleriyle filtrelenir. Yeni repolar yapılandırmaya dokunmadan devreye
  girer.
- **Grafiği dört yoldan taze tutar.** Doğrulanmış push webhook'ları, periyodik
  tarama, açık CI tetikleyicisi ve manuel yeniden indeksleme.
- **MCP'yi HTTP üzerinden konuşur.** Herhangi bir MCP istemcisi — Claude Code,
  Cursor, Copilot, chatbot, pipeline — tek bir uca OIDC token'ıyla bağlanır.
- **LDAP ile kimlik doğrular.** Active Directory veya OpenLDAP, Keycloak
  üzerinden federe edilir; gateway kendi kullanıcı tablosunu tutmaz.
- **Squad bazında izole eder, üç bağımsız katmanla.** Gateway'de rol
  yetenekleri ve proje allowlist'i, motorun kendi fail-closed araç profili ve
  kiracı başına dosya sistemi kökleri. Birindeki hata diğerlerini açmaz.
- **LiteLLM ile akıl ekler.** Değişiklik etkisi anlatımı ve doğal dilde
  sorular; hosted model, vLLM veya Ollama ile — kod değişikliği değil, proxy
  yapılandırması meselesi.
- **Her şeyi denetler.** Çağrı başına tek satır JSON kaydı, redler dahil;
  çünkü `get_code_snippet` gerçek kaynak kod döndürür.

## Mimari, tek bakışta

```
 Agent · Chatbot · CI ──MCP over HTTP + OIDC──▶ Gateway ──stdio──▶ CBM (kiracı başına)
                                                  │
                                                  └──HTTPS──▶ LiteLLM ──▶ model

 GitHub · GitLab · Bitbucket ──webhook/zamanlama──▶ Indexer ──▶ graph deposu
```

Ayrıntı: [docs/architecture.md](docs/architecture.md) (İngilizce).

## Hızlı başlangıç

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp/deploy

cp tenants.example.yaml tenants.yaml     # roller, squad'lar, proje izinleri
cp scan.example.yaml scan.yaml           # hangi org/grup indekslenecek

export LITELLM_MASTER_KEY=$(openssl rand -hex 24)
export GITHUB_TOKEN=ghp_...              # keşif için salt-okunur token
export CI_TRIGGER_TOKEN=$(openssl rand -hex 24)

docker compose up --build
```

Ardından keşfi ve indekslemeyi başlatın:

```bash
curl -X POST http://localhost:8082/rescan -H "Authorization: Bearer $CI_TRIGGER_TOKEN"
curl http://localhost:8082/repos
```

MCP istemcisini `http://localhost:8080/mcp` adresine, OIDC bearer token'ı ve
`X-Tenant` başlığıyla yöneltin. Keycloak ve LDAP kurulumu dahil tam anlatım:
[docs/deployment.md](docs/deployment.md).

## Yapılandırma

İki dosya; ikisi de commit'lenebilir — tüm sırlar ortamdan gelir.

`tenants.yaml` — kim, neyi, hangi veriye yapabilir:

```yaml
roles:
  admin:     [platform-admins]
  developer: [squad-payments]
  devops:    [chapter-devops]

tenants:
  payments:
    ldap_groups: [squad-payments, chapter-devops]
    tool_profile: analysis          # salt-okunur motor yüzeyi
    projects: ["acme-payments-*", "acme-ledger"]
```

`scan.yaml` — ne indekslenecek:

```yaml
connectors:
  - name: acme-github
    type: github
    org: acme
    token_env: GITHUB_TOKEN
    tenant: payments
    include: ["payments-*"]
    exclude: ["*-archive"]
    mode: moderate
```

## Dokümantasyon

Dokümantasyon İngilizcedir.

| | |
| --- | --- |
| [Architecture](docs/architecture.md) | bileşenler, veri akışı, henüz yapılmayanlar |
| [Engine constraints](docs/cbm-constraints.md) | tasarımı belirleyen, kaynak koddan doğrulanmış CBM davranışları |
| [Roles and permissions](docs/roles-and-permissions.md) | yetenekler, roller, chapter'lar |
| [Deployment](docs/deployment.md) | Keycloak/LDAP, webhook, CI, üretim notları |
| [Roadmap](docs/roadmap.md) | yapılan, sıradaki ve açıkça planlanmayan |
| [Decision records](docs/adr/) | tasarımın gerekçeleri |

## Durum

Erken aşama. Gateway ve indexer çalışıyor ve testlerle kaplı; web arayüzü ve
graph geçmişi tasarlandı ama yazılmadı. [docs/roadmap.md](docs/roadmap.md)
hangisinin hangisi olduğunu açıkça yazar — bir özelliğin var olduğunu
varsaymadan önce okuyun.

## Geliştirme

```bash
cd gateway && pip install -e '.[dev]' && pytest
cd ../indexer && pip install -e '.[dev]' && pytest
```

Katkılar açıktır — bkz. [CONTRIBUTING.md](CONTRIBUTING.md).

## Lisans

MIT; sarmaladığı motorla aynı. Bkz. [LICENSE](LICENSE).

`repo-mcp` bağımsız bir projedir; codebase-memory-mcp geliştiricileriyle
bağlantılı veya onlar tarafından onaylanmış değildir.
