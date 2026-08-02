# repo-mcp

**Tüm şirketin ortak kullandığı kod zekası servisi.** Bir GitHub organizasyonu,
GitLab grubu ya da Bitbucket workspace'i veriyorsun; altındaki bütün repolar
tek bir graph'a dönüşüyor. Coding agent'lar, chatbot'lar ve CI pipeline'ları
bu graph'a MCP ile bağlanıyor.

Sürüm 0.1.0 · [English](README.en.md) · [Değişiklikler](CHANGELOG.md)

---

"Bu fonksiyonu kim çağırıyor?", "Burayı değiştirirsem ne kırılır?", "Bu
endpoint'e hangi servisler gidiyor?" diye soruyorsun. Cevap context
penceresinden tahmin edilmiyor, kodun kendisinden hesaplanıyor.

Servis olarak çalışıyor: LDAP ile giriş, takım bazında izolasyon, role göre
yetki, repoların otomatik bulunması, audit log ve kendi
[LiteLLM](https://github.com/BerriAI/litellm) proxy'nden geçen bir LLM katmanı.
Modeli sen seçiyorsun — dışarıdan bir servis, kendi vLLM'in ya da Ollama.

## Neden

Kod zekası araçları tek geliştirici, tek laptop için tasarlanıyor. Şirket
ölçeğinde bu tutmuyor: herkes aynı repoları tekrar tekrar indexliyor, takımlar
arasında hiçbir graph paylaşılmıyor, servisler arası sorulara cevap
alınamıyor, ve bu bilgiye bir bottan veya CI job'ından erişilemiyor.

repo-mcp bunu ortak bir servise çeviriyor. Bir kez, merkezde indexleniyor.
Erişim kontrolü de bir şirketin gerçekten ihtiyaç duyduğu şekilde.

## Ne yapıyor

- **Repoları kendi buluyor.** Her GitHub org'u, GitLab grubu (alt gruplarıyla)
  veya Bitbucket workspace'i için bir connector tanımlıyorsun, pattern'lerle
  filtreliyorsun. Yeni açılan repo ayara dokunmadan devreye giriyor.
- **Graph'ı dört yoldan güncel tutuyor.** İmzası doğrulanmış push webhook'ları,
  periyodik tarama, CI'dan tetikleme, ve elle yeniden indexleme.
- **MCP'yi HTTP üzerinden konuşuyor.** Claude Code, Cursor, Copilot, bir bot ya
  da pipeline — MCP konuşan her client tek bir endpoint'e OIDC token'ıyla
  bağlanıyor.
- **Kimliği LDAP'tan alıyor.** Active Directory veya OpenLDAP, Keycloak
  üzerinden. repo-mcp kendi user tablosunu tutmuyor.
- **Takımları birbirinden ayırıyor, üç ayrı katmanda.** Gateway'de rol yetkisi
  ve proje listesi, engine içinde kapalı-varsayılan tool profili, dosya
  sisteminde takım başına ayrı dizin. Birindeki hata diğerlerini açmıyor.
- **Gerektiğinde düz metinle cevap veriyor.** Değişikliğin etkisini özetliyor,
  doğal dildeki soruları yanıtlıyor — ama önce mutlaka graph'ı sorguluyor.
  Modelden graph'ı tahmin etmesi hiç istenmiyor.
- **Her çağrıyı audit log'a yazıyor**, reddedilenler dahil. Bir kod parçasını
  okumak gerçek kaynak kodu okumak demek.

## Mimari

```
 Agent · Bot · CI ──MCP / HTTP + OIDC──▶ Gateway ──▶ engine (takım başına)
                                            │
                                            └──HTTPS──▶ LiteLLM ──▶ model

 GitHub · GitLab · Bitbucket ──webhook / zamanlama──▶ Indexer ──▶ graph
```

İki servis ve bir veritabanı.

**Gateway** kimlik doğrular, yetkiyi kontrol eder, MCP tarafını sunar.
**Indexer** repoları bulur ve graph'larını günceller.
**PostgreSQL** ayarları tutar: takımlar, roller, connector'lar, tercihler ve
şifrelenmiş provider token'ları. Admin bunları sistem çalışırken bir API'den
değiştirir, restart gerekmez.

Detay: [docs/architecture.md](docs/architecture.md).

## Hızlı başlangıç

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp

make setup      # venv'ler, bağımlılıklar, config dosyaları, secret'lar
# deploy/.env içine bir provider token'ı gir, deploy/scan.yaml'ı düzenle
make up         # Docker stack'i ayağa kaldır
make smoke      # uçtan uca kontrol et
```

Sonra tarama ve indexleme başlat:

```bash
source deploy/.env
curl -X POST http://localhost:8082/rescan -H "Authorization: Bearer $CI_TRIGGER_TOKEN"
curl http://localhost:8082/repos
```

MCP client'ını `http://localhost:8080/mcp` adresine yönlendir; OIDC token'ını
ve `X-Tenant` header'ını gönder. Keycloak ve LDAP kurulumu dahil tam anlatım
[docs/deployment.md](docs/deployment.md) içinde.

Bir şey çalışmazsa `make debug` çalıştır. Toolchain'i, engine'i, config'i,
storage'ı, iki servisi, canlı bir MCP çağrısını ve model tarafını sırayla
dener. İlk hatada durmaz, ne bulduysa hepsini söyler.

## Ayarlar

Ayarlar PostgreSQL'de. Dosya düzenleyerek değil, admin API'si veya
`repo-mcp-admin` ile değiştiriliyor. Environment'ta sadece veritabanı
okunmadan önce bilinmesi gerekenler kalıyor: `DATABASE_URL`, `SECRETS_KEY` ve
engine yolları.

Aşağıdaki iki format, hem import'un hem API'nin kabul ettiği şekil.

Kim, neyi, hangi veri üzerinde yapabilir:

```yaml
roles:
  admin:     [platform-admins]
  developer: [squad-payments]
  devops:    [chapter-devops]

tenants:
  payments:
    ldap_groups: [squad-payments, chapter-devops]
    tool_profile: analysis          # sadece okuma yapan engine profili
    projects: ["acme-payments-*", "acme-ledger"]
```

Ne indexlenecek:

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

## Nasıl görünüyor

Sistemin arayüzü yok — MCP endpoint'i, admin API'si ve health endpoint'leri
var. Aşağıdakiler çalışan bir kurulumdan alındı, `make screenshots` ile
yeniden üretiliyor.

Kurulum: şema, ayarlar ve ilk admin tek komutta.

![Kurulum](docs/images/01-bootstrap.svg)

Gateway hangi takımların yüklü olduğunu ve hangi config generation'da olduğunu
söylüyor.

![Hazır olma](docs/images/02-readyz.svg)

MCP çağrısı: client tool'ları listeliyor, yetkisi neye yetiyorsa onu görüyor.

![MCP tool listesi](docs/images/03-mcp-tools.svg)

Yetkisiz istek sessizce boş dönmüyor, sebebiyle birlikte reddediliyor.

![Reddedilen istek](docs/images/04-denied.svg)

Admin API'sinde bir ayarı değiştiriyorsun, generation numarası artıyor, bütün
kopyalar restart olmadan yeni değeri alıyor.

![Admin API](docs/images/05-admin.svg)

## Dokümantasyon

Dokümanlar İngilizce.

| | |
| --- | --- |
| [Architecture](docs/architecture.md) | bileşenler, veri akışı, henüz yapılmayanlar |
| [Roles and permissions](docs/roles-and-permissions.md) | yetkiler, roller, chapter'lar |
| [Deployment](docs/deployment.md) | Keycloak/LDAP, webhook, CI, production notları |
| [Environments](docs/environments.md) | bir branch nasıl çalışan bir şeye dönüşüyor |
| [Scaling](docs/scaling.md) | storage seçenekleri, izlenecek metrikler, kapasite |
| [Development](docs/development.md) | scriptler, test katmanları, debug |
| [Code standards](docs/code-standards.md) | kod, test ve doküman kuralları |
| [Branching](docs/branching.md) | main/dev akışı, secret'ların repoya girmemesi |
| [Indexing engine](docs/engine.md) | engine ne yapıyor, hangi sınırları getiriyor |
| [Roadmap](docs/roadmap.md) | yapılan, sıradaki, ve yapılmayacak olan |
| [Decision records](docs/adr/) | tasarım kararlarının gerekçeleri |

## Durum

Erken aşama, sürüm 0.1.0.

Gateway ve indexer çalışıyor, testleri var. Web arayüzü ve graph geçmişi
tasarlandı ama yazılmadı. Provider taraması, webhook'lar ve LLM katmanı
yazıldı ve unit testleri var, ama gerçek bir GitHub org'una, canlı bir LiteLLM
proxy'sine veya Keycloak'a karşı hiç çalıştırılmadı.

Ne hangi durumda, [docs/roadmap.md](docs/roadmap.md) ve
[memory-bank/progress.md](memory-bank/progress.md) açık açık yazıyor. Bir
özelliğin var olduğunu varsaymadan önce oraya bak.

## Geliştirme

```bash
make setup      # venv'ler ve bağımlılıklar
make test       # iki servis için lint ve unit testler
make dev        # iki servisi lokalde çalıştır, Docker'sız, auto-reload
make debug      # ne çalışmıyorsa bul
make verify     # bitirmeden önce geçilmesi gereken kontrol
make help       # gerisi
```

Her hedef [`scripts/`](scripts/) altında bir script; istersen doğrudan
çalıştır. Detay: [docs/development.md](docs/development.md).

Kubernetes için [`deploy/helm/repo-mcp`](deploy/helm/repo-mcp) chart'ı var.
Replica sayısını artırmadan önce [docs/scaling.md](docs/scaling.md) oku —
storage yapısı buna sınır koyuyor.

Sürüm numarası tek bir yerde, [`VERSION`](VERSION) dosyasında.
`scripts/version.sh` onu paketlere ve chart'a yayıyor, `make verify` de
hepsinin aynı şeyi söylediğini kontrol ediyor.

Katkıya açık: [CONTRIBUTING.md](CONTRIBUTING.md).

## Lisans

MIT — [LICENSE](LICENSE).

repo-mcp üçüncü taraf bir indexleme engine'i paketliyor. Lisansı ve atfı
[NOTICE](NOTICE) dosyasında.
