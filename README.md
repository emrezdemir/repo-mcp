# repo-mcp

**Şirket geneline yayılan, merkezî kod zekâsı.** Bir GitHub organizasyonunu,
GitLab grubunu ya da Bitbucket alanını verirsiniz; altındaki bütün depolar
sorgulanabilir tek bir bilgi grafiğine dönüşür. Kodlama asistanları,
sohbet botları ve CI hatları bu grafiğe MCP üzerinden bağlanır.

Sürüm 0.1.0 · [English](README.en.md) · [Sürüm notları](CHANGELOG.md)

---

*"Bu fonksiyonu kim çağırıyor?"*, *"Burayı değiştirirsem ne kırılır?"*,
*"Bu uca hangi servisler gidiyor?"* diye sorarsınız. Cevap bir bağlam
penceresinden tahmin edilmez; kodun kendisinden hesaplanır.

repo-mcp herkesin ortak kullandığı bir servis olarak çalışır: LDAP ile giriş,
takım bazında yalıtım, role göre yetki, depoların kendiliğinden bulunması,
denetim kaydı ve kendi [LiteLLM](https://github.com/BerriAI/litellm)
vekilinizden geçen bir akıl yürütme katmanı. Modeli siz seçersiniz — dışarıdan
servis, kendi vLLM'iniz ya da Ollama.

## Neden

Kod zekâsı araçları tek geliştiriciye, tek dizüstüne göre tasarlanır. Bir şirket
için yanlış ölçek: herkes aynı depoları yeniden indeksler, takımlar arasında
hiçbir grafik paylaşılmaz, servisler arası sorular hiç cevaplanamaz, ve bu
bilginin hiçbirine bir bottan ya da CI işinden erişilemez.

repo-mcp bunu ortak bir servise çevirir. Bir kez, merkezde indekslenir; erişim
denetimi de bir şirketin gerçekten ihtiyaç duyduğu biçimdedir.

## Ne yapar

- **Depoları kendiliğinden bulur.** Her GitHub organizasyonu, GitLab grubu
  (iç içe alt gruplarıyla) veya Bitbucket alanı için bir bağlayıcı tanımlarsınız;
  desenlerle süzersiniz. Açılan yeni depo, ayara elinizi sürmeden dahil olur.
- **Grafiği dört yoldan taze tutar.** İmzası doğrulanmış push kancaları,
  düzenli tarama, CI'dan tetikleme ve elle yeniden indeksleme.
- **MCP'yi HTTP üzerinden konuşur.** Claude Code, Cursor, Copilot, bir bot ya da
  bir hat — MCP konuşan her istemci tek bir uca, OIDC anahtarıyla bağlanır.
- **Kimliği LDAP'tan alır.** Active Directory veya OpenLDAP, Keycloak üzerinden
  bağlanır. repo-mcp kendi kullanıcı tablosunu tutmaz.
- **Takımları birbirinden yalıtır, üç bağımsız katmanla.** Ağ geçidinde rol
  yetkileri ve proje listesi; motorun içinde kapalı-varsayılan araç profili;
  dosya sisteminde takım başına ayrı kök. Birindeki hata diğerlerini açmaz.
- **Gerektiğinde düz metinle cevaplar.** Değişikliğin etkisini özetler,
  doğal dilde soruları yanıtlar — ama her zaman önce grafiği sorgulayarak.
  Modelden grafiği tahmin etmesi hiçbir zaman istenmez.
- **Her çağrıyı denetim kaydına yazar**, reddedilenler dahil. Bir kod parçasını
  okumak, gerçek kaynak kodu okumak demektir.

## Mimari

```
 Asistan · Bot · CI ──MCP / HTTP + OIDC──▶ Ağ geçidi ──▶ indeksleme motoru
                                              │           (takım başına bir süreç)
                                              └──HTTPS──▶ LiteLLM ──▶ model

 GitHub · GitLab · Bitbucket ──kanca / zamanlama──▶ İndeksleyici ──▶ grafik deposu
```

İki servis ve bir veritabanı.

**Ağ geçidi** kimliği doğrular, yetkiyi denetler ve MCP yüzeyini sunar.
**İndeksleyici** depoları bulur ve grafiklerini güncel tutar.
**PostgreSQL** ayarları tutar — takımlar, roller, bağlayıcılar, tercihler ve
şifrelenmiş sağlayıcı anahtarları. Yönetici bunları sistem çalışırken bir API
üzerinden değiştirir; yeniden başlatmak gerekmez.

Ayrıntı: [docs/architecture.md](docs/architecture.md).

## Hızlı başlangıç

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp

make setup      # sanal ortamlar, bağımlılıklar, ayar dosyaları, üretilen sırlar
# deploy/.env içine bir sağlayıcı anahtarı girin, deploy/scan.yaml'ı düzenleyin
make up         # Docker yığınını ayağa kaldır
make smoke      # uçtan uca doğrula
```

Ardından tarama ve indeksleme başlatın:

```bash
source deploy/.env
curl -X POST http://localhost:8082/rescan -H "Authorization: Bearer $CI_TRIGGER_TOKEN"
curl http://localhost:8082/repos
```

MCP istemcinizi `http://localhost:8080/mcp` adresine yöneltin; OIDC anahtarını
ve `X-Tenant` başlığını gönderin. Keycloak ve LDAP kurulumu dahil tam anlatım
[docs/deployment.md](docs/deployment.md) içinde.

Bir şey yürümezse `make debug` çalıştırın. Araç zincirini, motoru, ayarları,
depolamayı, iki servisi, canlı bir MCP gidiş-dönüşünü ve model tarafını
sırayla dener; ilk hatada durmaz, bulduğu her şeyi raporlar.

## Ayarlar

Ayarlar PostgreSQL'de durur. Dosya düzenleyerek değil, yönetim API'si veya
`repo-mcp-admin` ile değiştirilir. Ortam değişkenlerinde yalnızca veritabanı
okunmadan önce bilinmesi gerekenler kalır: `DATABASE_URL`, `SECRETS_KEY` ve
motor yolları.

Aşağıdaki iki biçim, hem içe aktarıcının hem de API'nin kabul ettiği şekildir.

Kim, neyi, hangi veri üzerinde yapabilir:

```yaml
roles:
  admin:     [platform-admins]
  developer: [squad-payments]
  devops:    [chapter-devops]

tenants:
  payments:
    ldap_groups: [squad-payments, chapter-devops]
    tool_profile: analysis          # salt okunur motor yüzeyi
    projects: ["acme-payments-*", "acme-ledger"]
```

Ne indekslenecek:

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

Sistemin kendisi bir arayüz sunmaz — MCP ucu, yönetim API'si ve sağlık
uçlarından ibarettir. Aşağıdakiler çalışan bir kurulumdan alınmıştır.

Hazırlık: şema, ayarlar ve ilk yönetici tek komutta kurulur.

![Kurulum ve hazırlık](docs/images/01-bootstrap.svg)

Ağ geçidi hangi takımların yüklendiğini ve hangi ayar kuşağında olduğunu söyler.

![Hazır olma çıktısı](docs/images/02-readyz.svg)

MCP gidiş-dönüşü: istemci araçları listeler, yetkisi neye yetiyorsa onu görür.

![MCP araç listesi](docs/images/03-mcp-tools.svg)

Yetkisiz bir istek sessizce boş dönmez; nedenini söyleyerek reddedilir.

![Reddedilen istek](docs/images/04-denied.svg)

Yönetim API'si: ayarı değiştirirsiniz, kuşak numarası ilerler, bütün kopyalar
yeniden başlatılmadan yeni değeri alır.

![Yönetim API'si](docs/images/05-admin.svg)

## Belgeler

Belgeler İngilizcedir.

| | |
| --- | --- |
| [Architecture](docs/architecture.md) | bileşenler, veri akışı, henüz yapılmamış olanlar |
| [Roles and permissions](docs/roles-and-permissions.md) | yetkiler, roller, chapter'lar |
| [Deployment](docs/deployment.md) | Keycloak/LDAP, kancalar, CI, üretim notları |
| [Environments](docs/environments.md) | bir dalın nasıl çalışan bir şeye dönüştüğü |
| [Scaling](docs/scaling.md) | depolama düzenleri, izlenecek ölçütler, kapasite |
| [Development](docs/development.md) | betikler, test katmanları, hata ayıklama |
| [Code standards](docs/code-standards.md) | bağlayıcı kod, test ve belge kuralları |
| [Branching](docs/branching.md) | main/dev akışı, sırların repoya girmemesi |
| [Indexing engine](docs/engine.md) | gömülü motor ne yapar, hangi sınırları dayatır |
| [Roadmap](docs/roadmap.md) | yapılan, sıradaki ve açıkça planlanmayan |
| [Decision records](docs/adr/) | tasarımın gerekçeleri |

## Durum

Erken aşama, sürüm 0.1.0.

Ağ geçidi ve indeksleyici çalışıyor ve testlerle kaplı. Web arayüzü ile grafik
geçmişi tasarlandı ama yazılmadı. Sağlayıcı taraması, kancalar ve model
katmanı yazıldı ve birim testleri var, ancak gerçek bir GitHub organizasyonuna,
canlı bir LiteLLM vekiline veya Keycloak'a karşı hiç çalıştırılmadı.

Neyin hangi durumda olduğunu [docs/roadmap.md](docs/roadmap.md) ve
[memory-bank/progress.md](memory-bank/progress.md) açıkça yazar — bir özelliğin
var olduğunu varsaymadan önce oraya bakın.

## Geliştirme

```bash
make setup      # sanal ortamlar ve bağımlılıklar
make test       # her iki servis için lint ve birim testleri
make dev        # iki servisi yerelde çalıştır, Docker'sız, otomatik yeniden yükleme
make debug      # ne çalışmıyorsa teşhis et
make verify     # bitirmeden önce geçilmesi gereken kapı
make help       # geri kalanı
```

Her hedef [`scripts/`](scripts/) altında bir betiktir; istersen doğrudan
çalıştırırsın. Ayrıntı: [docs/development.md](docs/development.md).

Kubernetes kurulumu [`deploy/helm/repo-mcp`](deploy/helm/repo-mcp) chart'ını
kullanır. Herhangi bir kopya sayısını artırmadan önce
[docs/scaling.md](docs/scaling.md) okuyun — depolama düzeni bunu sınırlar.

Sürüm numarası tek bir yerde, [`VERSION`](VERSION) dosyasında durur;
`scripts/version.sh` onu paketlere ve chart'a taşır, `make verify` de
hepsinin aynı şeyi söylediğini denetler.

Katkılar açıktır: [CONTRIBUTING.md](CONTRIBUTING.md).

## Lisans

MIT — [LICENSE](LICENSE).

repo-mcp üçüncü taraf bir indeksleme motoru paketler. Lisansı ve atfı
[NOTICE](NOTICE) dosyasındadır.
