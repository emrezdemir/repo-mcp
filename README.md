<div align="center">

# repo-mcp

**Şirketin bütün kodu tek bir graph'ta.**

GitHub, GitLab ve Bitbucket repository'lerinizi tek yerden indeksler; ortaya
çıkan kod graph'ını MCP üzerinden coding agent'lara, chatbot'lara ve CI'a açar.

[**Site**](https://emrezdemir.github.io/repo-mcp/) ·
[**Belgeler**](https://emrezdemir.github.io/repo-mcp/docs/) ·
[English](README.en.md) ·
[Değişiklikler](CHANGELOG.md)

Sürüm 0.3.0 · MIT

</div>

<img src="docs/images/ui-graph.png" alt="854 düğüm ve 4.454 kenarlı bir kod graph'ının 3D görünümü">

---

## Ne işe yarar

Bir GitHub organizasyonunu, GitLab grubunu veya Bitbucket workspace'ini
connector olarak tanımlarsınız; kapsamdaki repository'ler bulunur, klonlanır ve
indekslenir. Çıkan graph'a **MCP** ile erişilir (HTTP üzerinde JSON-RPC). Gelen
istek **OIDC** token'ıyla doğrulanır, kullanıcının **LDAP** grupları bir role ve
bir takıma çevrilir.

|  |  |
| --- | --- |
| **Bir kez indekslenir** | Aynı repository herkesin makinesinde yeniden indekslenmez |
| **Takım bazlı izolasyon** | Her takım kendi kodunu ayrıntısıyla, diğerlerini yalnızca yapı olarak görür |
| **Üç bağımsız yetki katmanı** | Rolün yetkileri ∩ proje listesi ∩ motorun tool profili; üstüne takıma özel kök dizin |
| **Restart yok** | Yapılandırma PostgreSQL'de; değişiklik bir sayaç üzerinden servislere ulaşır |
| **Cevap graph'tan** | `ask_codebase` önce graph sorgusu çalıştırır, modelden tahmin istenmez |
| **İki yönetim yüzeyi** | Terminal ve web konsolu aynı fonksiyonları çağırır, aynı audit kaydını bırakır |

## Beş dakikada kurulum

Docker Engine 24+ ve Compose v2 yeterli.

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp && make setup     # beş soru -> deploy/.env
make up                       # şema, ilk yönetici, servisler
```

Ardından bir connector tanımlayın — terminalden ya da
`http://localhost:8080/ui` adresindeki konsoldan; ikisi de aynı fonksiyonu
çağırır:

```bash
repo-mcp-admin secret set connector.acme-github.token
repo-mcp-admin connector set acme-github \
  --provider github --squad payments --setting org=acme \
  --token-secret connector.acme-github.token

repo-mcp-admin connector check acme-github
# acme-github: ok — 34 of 41 repositories would be indexed
```

`check`, provider'a sorup connector'ın gerçekten ne göreceğini söyler; bir şey
yanlışsa hangisi olduğunu yazar. Docker'sız geliştirmek için `make dev`.

## Arayüz

<table>
<tr>
<td width="50%"><img src="docs/images/ui-ask.png" alt="Doğal dille soru sorma"></td>
<td width="50%"><img src="docs/images/ui-projects.png" alt="İndekslenmiş projeler"></td>
</tr>
<tr>
<td><b>Sorun.</b> Cevap graph'tan gelen kanıta dayanır, adı geçen sembolleri gösterir.</td>
<td><b>Projeler.</b> Takımın indekslediği her şey; sağlığı ve ADR'siyle.</td>
</tr>
<tr>
<td><img src="docs/images/ui-admin.png" alt="Yönetim konsolu"></td>
<td><img src="docs/images/ui-signin.png" alt="Giriş ekranı"></td>
</tr>
<tr>
<td><b>Yönetin.</b> Takımlar, roller, connector'lar, secret'lar, ayarlar, audit.</td>
<td><b>Girin.</b> PKCE'li Authorization Code; tarayıcı public client.</td>
</tr>
</table>

Arayüz sıfırdan yazılmadı: motorun kendi arayüzü (React + Three.js, MIT) alınıp
bu platforma bağlandı. Gerekçesi
[ADR-0011](docs/adr/0011-adopt-the-upstream-interface.md) içinde.

## Bağlanmak

```bash
curl -s http://localhost:8080/mcp \
  -H "Authorization: Bearer $OIDC_TOKEN" \
  -H "X-Tenant: payments" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

`tools/list` çıktısı çağırana göre değişir: rolün yetkisi olmayan ya da takımın
tool profilinde bulunmayan bir tool listeye girmez.

## Belgeler

Sistemin bütün belgeleri sitede — nasıl kullanılır, senaryolar, ekran
görüntüleri ve kararların gerekçesi:
**[emrezdemir.github.io/repo-mcp/docs](https://emrezdemir.github.io/repo-mcp/docs/)**

| | |
| --- | --- |
| [Mimari](https://emrezdemir.github.io/repo-mcp/docs/architecture.html) | İki servis, bir motor, paylaşılan graph dizini |
| [Web arayüzü](https://emrezdemir.github.io/repo-mcp/docs/web-interface.html) | Nasıl kurulu, giriş nasıl çalışıyor, ne yapmıyor |
| [Yönetim](https://emrezdemir.github.io/repo-mcp/docs/administration.html) | Terminal ve konsol, yan yana |
| [Roller ve yetkiler](https://emrezdemir.github.io/repo-mcp/docs/roles-and-permissions.html) | Rol ne yapar, takım neye erişir |
| [Kurulum](https://emrezdemir.github.io/repo-mcp/docs/deployment.html) | Compose, Kubernetes, Keycloak ve LDAP |
| [Ortamlar](https://emrezdemir.github.io/repo-mcp/docs/environments.html) | Branch'ten artifact'e, artifact'ten ortama |
| [Ölçekleme](https://emrezdemir.github.io/repo-mcp/docs/scaling.html) | Replika, kuyruk ve depolama |
| [Kararlar](https://emrezdemir.github.io/repo-mcp/docs/adr/0001-wrap-dont-fork.html) | Neden fork edilmedi, neden veritabanı, neden bu arayüz |
| [Geliştirme](https://emrezdemir.github.io/repo-mcp/docs/development.html) | Yerel kurulum, testler, katkı akışı |

Belgelerin kaynağı [`docs/`](docs/) altındaki markdown dosyaları; site onlardan
üretiliyor, yani iki kopya arasında fark oluşmuyor. Referans belgeleri
İngilizce, tanıtım sayfaları Türkçe.

## Katkı ve güvenlik

Katkı akışı [CONTRIBUTING.md](CONTRIBUTING.md), güvenlik bildirimi
[SECURITY.md](SECURITY.md) içinde. Branch adları `feature/`, `bugfix/`,
`hotfix/`, `chore/` veya `docs/` ile başlar; birleştirmeden önceki kapı
`make verify`.

## Lisans

MIT — [LICENSE](LICENSE). İndeksleme motoru
[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) (MIT)
sarmalanarak kullanılıyor, fork edilmiyor; ayrıntısı [NOTICE](NOTICE) içinde.
