<div align="center">

# repo-mcp

**Şirketin bütün kodu, tek bir graph.**

GitHub, GitLab ve Bitbucket repository'lerini merkezî olarak indeksler, kod
graph'ını MCP üzerinden coding agent'lara, chatbot'lara ve CI'a açar.

[**Site**](https://emrezdemir.github.io/repo-mcp/) ·
[English](README.en.md) ·
[Belgeler](docs/) ·
[Değişiklikler](CHANGELOG.md)

Sürüm 0.3.0 · MIT

</div>

<img src="docs/images/ui-graph.png" alt="854 düğüm ve 4.454 kenarlı bir kod graph'ının 3D görünümü">

---

## Ne yapar

Bir GitHub organizasyonu, GitLab grubu veya Bitbucket workspace'i connector
olarak tanımlanır; kapsamdaki repository'ler keşfedilir, klonlanır ve
indekslenir. Elde edilen graph'a erişim **MCP** ile olur (HTTP üzerinde
JSON-RPC). Erişim **OIDC** token'ı ile doğrulanır, **LDAP** grup üyeliğine göre
role ve takıma çevrilir.

|  |  |
| --- | --- |
| **Bir kez indeksle** | Aynı repository herkesin makinesinde yeniden indekslenmez |
| **Takım bazlı izolasyon** | Her takım kendi kodunu detayda, diğerlerini yalnızca topolojide görür |
| **Üç bağımsız yetki katmanı** | Rol yetkileri ∩ proje allowlist'i ∩ motor tool profili, üstüne takım başına dosya kökü |
| **Restart yok** | Yapılandırma PostgreSQL'de; değişiklik generation sayacıyla servislere ulaşır |
| **Graph'tan cevap** | `ask_codebase` önce graph sorgusu çalıştırır; modelden tahmin istenmez |
| **İki yönetim yüzeyi** | Terminal ve web konsolu aynı fonksiyonları çağırır, aynı audit'i üretir |

## Beş dakikada kurulum

Docker Engine 24+ ve Compose v2 yeter.

```bash
git clone https://github.com/emrezdemir/repo-mcp
cd repo-mcp && make setup     # beş soru -> deploy/.env
make up                       # şema, ilk yönetici, servisler
```

Sonra bir connector tanımla — terminalden ya da `http://localhost:8080/ui`
üzerindeki konsoldan; ikisi aynı fonksiyonu çağırır:

```bash
repo-mcp-admin secret set connector.acme-github.token
repo-mcp-admin connector set acme-github \
  --provider github --squad payments --setting org=acme \
  --token-secret connector.acme-github.token
```

Docker'sız geliştirme için `make dev`.

## Arayüz

<table>
<tr>
<td width="50%"><img src="docs/images/ui-ask.png" alt="Doğal dille soru sorma"></td>
<td width="50%"><img src="docs/images/ui-projects.png" alt="İndekslenmiş projeler"></td>
</tr>
<tr>
<td><b>Sor.</b> Cevap graph kanıtına dayanır, andığı sembolleri gösterir.</td>
<td><b>Projeler.</b> Takımın indekslediği her şey, sağlığı ve ADR'siyle.</td>
</tr>
<tr>
<td><img src="docs/images/ui-admin.png" alt="Yönetim konsolu"></td>
<td><img src="docs/images/ui-signin.png" alt="Giriş ekranı"></td>
</tr>
<tr>
<td><b>Yönet.</b> Takımlar, roller, connector'lar, secret'lar, ayarlar, audit.</td>
<td><b>Gir.</b> PKCE ile Authorization Code; tarayıcı public client.</td>
</tr>
</table>

Arayüz sıfırdan yazılmadı: motorun kendi arayüzü (React + Three.js, MIT)
alınıp bu platforma bağlandı. Gerekçesi
[ADR-0011](docs/adr/0011-adopt-the-upstream-interface.md) içinde.

## Bağlanmak

```bash
curl -s http://localhost:8080/mcp \
  -H "Authorization: Bearer $OIDC_TOKEN" \
  -H "X-Tenant: payments" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

`tools/list` çıktısı çağırana göre değişir: rolün yetkisi olmayan ve takımın
tool profilinde bulunmayan tool listeye girmez.

## Belgeler

Nasıl kullanılır, senaryolar ve ekran görüntüleri:
**[emrezdemir.github.io/repo-mcp](https://emrezdemir.github.io/repo-mcp/)**

| | |
| --- | --- |
| [Mimari](docs/architecture.md) | İki servis, bir motor, paylaşılan graph dizini |
| [Web arayüzü](docs/web-interface.md) | Nasıl kurulu, giriş nasıl çalışıyor, ne yapmıyor |
| [Yönetim](docs/administration.md) | Terminal ve konsol, yan yana |
| [Roller ve yetkiler](docs/roles-and-permissions.md) | Rol ne yapar, takım neye erişir |
| [Kurulum](docs/deployment.md) | Compose, Kubernetes, Keycloak ve LDAP |
| [Ortamlar](docs/environments.md) | Branch'ten artifact'e, artifact'ten ortama |
| [Ölçekleme](docs/scaling.md) | Replika, kuyruk ve depolama |
| [ADR'ler](docs/adr/) | Kararlar ve kabul edilen bedelleri |
| [Geliştirme](docs/development.md) | Yerel kurulum, testler, katkı akışı |

## Katkı ve güvenlik

Katkı akışı [CONTRIBUTING.md](CONTRIBUTING.md), güvenlik bildirimi
[SECURITY.md](SECURITY.md) içinde. Branch adları `feature/`, `bugfix/`,
`hotfix/`, `chore/` veya `docs/` ile başlar; `make verify` birleştirme
öncesindeki kapıdır.

## Lisans

MIT — [LICENSE](LICENSE). İndeksleme motoru
[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) (MIT)
sarmalanarak kullanılır, fork edilmez; ayrıntısı [NOTICE](NOTICE) içinde.
