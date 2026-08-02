# repo-mcp

**Organizasyon geneli merkezi kod zekâsı.** Bir GitHub organizasyonu, GitLab
grubu veya Bitbucket workspace'i verirsiniz; altındaki tüm repolar
sorgulanabilir bir bilgi grafiğine dönüşür — MCP üzerinden kodlama agent'ları,
chatbotlar ve CI pipeline'ları için.

[English](README.md)

---

*"Bu fonksiyonu kim çağırıyor?"*, *"Bunu değiştirirsem ne kırılır?"* veya
*"Bu endpoint'i hangi servisler çağırıyor?"* diye sorun; cevabı bir context
penceresinden tahmin edilmiş değil, kodun kendisinden hesaplanmış olarak alın.

repo-mcp tüm şirketin paylaştığı bir servis olarak çalışır: LDAP tabanlı giriş,
squad bazlı izolasyon, rol tabanlı yetkiler, otomatik repo keşfi, denetim kaydı
ve kendi [LiteLLM](https://github.com/BerriAI/litellm) proxy'nizden geçen bir
akıl katmanı — hosted model, vLLM veya Ollama, seçim sizin.

## Neden

Kod zekâsı araçları tek geliştirici, tek dizüstü için tasarlanmıştır. Bu bir
şirket için yanlış şekildir: her geliştirici aynı repoları yeniden indeksler,
takımlar arasında hiçbir graph paylaşılmaz, servisler arası sorular hiç
cevaplanamaz ve bu bilginin hiçbiri bir chatbot'tan veya CI işinden
erişilebilir değildir.

repo-mcp bunu paylaşımlı bir servise dönüştürür — merkezî olarak bir kez
indekslenmiş, bir organizasyonun gerçekten ihtiyaç duyduğu erişim kontrolüyle.

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
  üzerinden federe edilir; repo-mcp kendi kullanıcı tablosunu tutmaz.
- **Squad bazında izole eder, üç bağımsız katmanla.** Gateway'de rol
  yetenekleri ve proje allowlist'i, motor process'i içinde fail-closed araç
  profili ve kiracı başına dosya sistemi kökleri. Birindeki hata diğerlerini
  açmaz.
- **Gerektiğinde düz metinle cevaplar.** Pull request'ler için değişiklik
  etkisi özetleri ve doğal dilde sorular — her zaman önce bir graph sorgusuna
  dayanarak; modelden graph'i tahmin etmesi asla istenmez.
- **Her şeyi denetler.** Çağrı başına tek satır JSON kaydı, redler dahil;
  çünkü bir snippet okumak gerçek kaynak kodu okumak demektir.

## Mimari, tek bakışta

```
 Agent · Chatbot · CI ──MCP over HTTP + OIDC──▶ Gateway ──▶ indeksleme motoru
                                                  │          (kiracı başına)
                                                  └──HTTPS──▶ LiteLLM ──▶ model

 GitHub · GitLab · Bitbucket ──webhook/zamanlama──▶ Indexer ──▶ graph deposu
```

İki servis. **Gateway** kimlik doğrular, yetkilendirir ve MCP yüzeyini sunar.
**Indexer** repoları keşfeder ve graph'larını güncel tutar. İkisi de gömülü bir
indeksleme motorunu sürer; bkz. [docs/architecture.md](docs/architecture.md).

## Hızlı başlangıç

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp

make setup      # venv'ler, bağımlılıklar, config dosyaları, üretilmiş secret'lar
# deploy/.env (bir provider token'ı ekleyin) ve deploy/scan.yaml düzenleyin
make up         # Docker stack'ini kur ve başlat
make smoke      # uçtan uca doğrula
```

Ardından keşfi ve indekslemeyi başlatın:

```bash
source deploy/.env
curl -X POST http://localhost:8082/rescan -H "Authorization: Bearer $CI_TRIGGER_TOKEN"
curl http://localhost:8082/repos
```

MCP istemcisini `http://localhost:8080/mcp` adresine, OIDC bearer token'ı ve
`X-Tenant` başlığıyla yöneltin. Keycloak ve LDAP kurulumu dahil tam anlatım:
[docs/deployment.md](docs/deployment.md).

Bir şey çalışmazsa `make debug`; toolchain'i, motoru, yapılandırmayı, depolamayı,
iki servisi, gerçek bir MCP round-trip'ini ve model backend'ini kontrol eder —
ilk sorunda durmaz, bulduğu her şeyi raporlar.

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
| [Roles and permissions](docs/roles-and-permissions.md) | yetenekler, roller, chapter'lar |
| [Deployment](docs/deployment.md) | Keycloak/LDAP, webhook, CI, üretim notları |
| [Scaling](docs/scaling.md) | depolama topolojileri, izlenecek metrikler, kapasite |
| [Development](docs/development.md) | scriptler, test katmanları, hata ayıklama |
| [Indexing engine](docs/engine.md) | gömülü motor ne yapar ve hangi sınırları dayatır |
| [Roadmap](docs/roadmap.md) | yapılan, sıradaki ve açıkça planlanmayan |
| [Decision records](docs/adr/) | tasarımın gerekçeleri |

## Durum

Erken aşama. Gateway ve indexer çalışıyor ve testlerle kaplı; web arayüzü ve
graph geçmişi tasarlandı ama yazılmadı. [docs/roadmap.md](docs/roadmap.md)
hangisinin hangisi olduğunu açıkça yazar — bir özelliğin var olduğunu
varsaymadan önce okuyun.

## Geliştirme

```bash
make setup      # venv'ler ve bağımlılıklar
make test       # iki servis için lint ve birim testleri
make dev        # iki servisi lokalde çalıştır, Docker'sız, auto-reload
make debug      # çalışmayan neyse teşhis et
make e2e        # image'ları kur, gerçek repo indeksle, sorgula, kapat
make help       # geri kalan her şey
```

Her hedef [`scripts/`](scripts/) altında bir scripttir — isterseniz doğrudan
çalıştırın. Ayrıntı: [docs/development.md](docs/development.md).

Kubernetes kurulumu [`deploy/helm/repo-mcp`](deploy/helm/repo-mcp) chart'ını
kullanır; herhangi bir replica sayısını artırmadan önce
[docs/scaling.md](docs/scaling.md) okuyun — depolama topolojisi bunu
sınırlıyor.

Katkılar açıktır — bkz. [CONTRIBUTING.md](CONTRIBUTING.md).

## Lisans

MIT — bkz. [LICENSE](LICENSE).

repo-mcp üçüncü taraf bir indeksleme motoru paketler; lisansı ve atfı
[NOTICE](NOTICE) dosyasındadır.
