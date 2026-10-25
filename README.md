# Fürdőszoba fűtés – Home Assistant (HACS)

Fürdőszoba vezérlő padlófűtéshez (gázkazán OpenTherm-en + külön keringető szivattyú) és elektromos törölközőszárítóhoz (okos dugalj). A hozzá tartozó Lovelace kártyát az integráció automatikusan betölti.

**Cél:** a lehető legegyszerűbb kezelés (egy gomb: *Fürdés most*), és közben energiatakarékos, penész ellen védő működés.

---

## Mit csinál

### Padlófűtés
- **Fürdési időre 24 °C** (állítható). A padló lassú, ezért a rendszer **előre elindítja a fűtést**. Megtanulja, hány °C/óra sebességgel melegszik a fürdő, és ebből számolja ki, mikor kell indulnia (alapból legfeljebb 3 órával előtte).
- Egyébként **takarékos hőmérsékletet** tart (alapból 20 °C), ami a penész ellen is elég.
- **Nem szól bele a ház fűtésébe:**
  - Ha a ház fűtése **már megy** (OTGW termosztát hőt kér), csak a **szivattyú reléjét** kapcsolja be. A meleg víz már amúgy is kering.
  - Ha a kazán **áll**, OpenTherm-en hőt kér (control setpoint, alapból 45 °C előremenő). Ezt addig teszi, amíg a **visszatérő víz el nem éri a beállított hőfokot** (alapból 30 °C, ennyi kellemes a lábnak). Utána leveszi a kérést, a szivattyú pedig tovább keringet. 3 °C hűlés után újra kér.
  - Ha közben a ház termosztátja elkezd hőt kérni, **azonnal visszaadja** a vezérlést (control setpoint = 0).
- Home Assistant újraindításkor az OTGW integráció magától törli a felülbírálást, így a kazán sosem ragad bekapcsolva.

### Törölközőszárító
Bekapcsol, ha az alábbiak közül bármelyik teljesül:
1. **Napelemes akku** a küszöb felett van (alapból 90%, 5% hiszterézissel). Ilyenkor ingyen áramot használ.
2. **Napközben** (06–22 óra) **21 °C alatt** van a fürdő.
3. **Fürdés előtt** 20 percig, **fürdés alatt**, és **fürdés után** 30 percig. Ha utána még magas a pára, legfeljebb +60 percig tovább szárít.
4. **Penészvédelem:** ha a pára tartósan 75% felett van, szárít (kikapcsolható).
5. **Kézi gomb:** *Törölköző 30′*. Második nyomásra kikapcsol.

A fürdést a **páratartalom hirtelen emelkedéséből magától is felismeri** (zuhany), így gombnyomás nélkül is elindul a fürdés utáni szárítás.

### Pára, penész, szellőztetés
- Számolja a **harmatpontot**, a napi „70% feletti” perceket, és ebből a **penészkockázatot** (alacsony / közepes / magas).
- Ha a pára 10 percnél tovább a határ (65%) felett van, **értesítést küld**: *„Szellőztess!”*. Legfeljebb óránként egyszer.
- Ha megadsz **kültéri hőmérsékletet és páratartalmat**, csak akkor kér szellőztetést, ha kint **ténylegesen szárazabb a levegő** (abszolút páratartalom alapján). Különben a törölközőszárítóval szárít.
- Ha van **ablakérzékelő**: nyitott ablaknál szünetel a fűtés. Ha a pára már lement, szól, hogy **becsukhatod az ablakot**.

### Fogyasztás
A törölközőszárító fogyasztását **napi, heti, havi és éves** bontásban számolja, **kWh-ban és forintban** is. Az előző időszak (tegnap, előző hét…) is látszik. A forintot a fogyasztás idején érvényes áron számolja, így egy későbbi árváltozás nem írja át a múltat.

Forrás, ebben a sorrendben:
1. a dugalj **kWh** szenzora (legpontosabb),
2. a dugalj **W** szenzora,
3. a megadott **névleges teljesítmény** × bekapcsolt idő.

A *Törölköző energia összesen* szenzor felvehető a HA **Energia** irányítópultra is egyedi eszközként.

---

## Telepítés

1. HACS → jobb felső ⋮ → **Egyedi tárolók** → add meg a GitHub tároló címét, kategória: **Integráció**.
   (Kézi telepítés: másold a `custom_components/bathroom_heating` mappát a HA `config/custom_components/` mappájába.)
2. Indítsd újra a Home Assistantot.
3. **Beállítások → Eszközök és szolgáltatások → Integráció hozzáadása → „Fürdőszoba fűtés”**.

### A beállító varázsló 3 lépése
| Lépés | Mit kér |
|---|---|
| Alapok | fürdő hőmérő, páratartalom szenzor, **szivattyú relé**, **törölközőszárító dugalj** |
| Kazán | „ház fűtése megy?” entitás, a hőkérés módja, OTGW `gateway_id`, **visszatérő víz** szenzor |
| Kiegészítők | akku %, dugalj W/kWh, névleges W, ablakérzékelő, kültéri hőmérséklet/pára, értesítés (pl. `notify.mobile_app_telefon`) |

Később minden módosítható: integráció → **Konfigurálás**.

### OpenTherm Gateway tippek
- **gateway_id:** amit az OpenTherm Gateway integráció beállításakor megadtál (az eszköz adatainál is látszik).
- **Visszatérő víz szenzor:** az OTGW *Return Water Temperature* szenzora **alapból le van tiltva**, ezt engedélyezd az OTGW eszköz entitásai között.
- **„Ház fűtése megy?”:** válaszd az **OTGW climate (termosztát)** entitást. Amíg mi nem kérünk hőt, a `hvac_action` alapján dönt. Amikor mi kérünk, a termosztát saját hőmérséklet/cél értékéből dönt, hogy a saját kérésünket ne vegye a ház fűtésének. Bináris szenzor is megadható (pl. *Central heating enabled (thermostat)*).
- Ha nem OTGW-d van: választható **szám entitás** (pl. ESPHome OpenTherm előremenő hőfok), **kapcsoló**, vagy **„nincs”** (ekkor csak a szivattyút kapcsolja).

---

## Kártya

Az integráció a kártyát automatikusan regisztrálja, nem kell erőforrásként felvenni. Irányítópult → **Kártya hozzáadása → „Fürdőszoba fűtés”**, vagy YAML-ben:

```yaml
type: custom:bathroom-heating-card
entity: sensor.furdoszoba_allapot
title: Fürdőszoba
```

A kártyán:
- nagy szobahőmérséklet a célértékkel, páratartalom és penészkockázat,
- **napi idősáv:** fürdési idők (kék), előfűtés (narancs átmenet), törölközőszárító (csíkos), és a „most” jelölő,
- padlófűtés és törölközőszárító állapota **okkal együtt** (pl. „Napelem akku 93%”, „visszatérő 27,5° / 30°”),
- **Fürdés most / Fürdés vége**, **Törölköző 30′**,
- üzemmód: Automatikus · Komfort · Takarékos · Távol · Ki,
- fogyasztás: Ma / Hét / Hónap / Év, kWh + Ft, előző időszakkal,
- **Beállítások** (lenyitható): fürdési idők hétköznapra és hétvégére (időpont választóval), hőmérsékletek, küszöbök, áramár.

---

## Entitások (automatizáláshoz)

| Entitás | Leírás |
|---|---|
| `sensor.*_allapot` | szöveges állapot, attribútumokban minden adat |
| `select.*_uzemmod` | Automatikus / Komfort / Takarékos / Távol / Ki |
| `button.*_furdes_most`, `*_furdes_vege`, `*_torolkozo_30_perc` | gyors műveletek |
| `text.*_furdesi_idok_hetkoznap` / `_hetvegen` | pl. `06:30-07:00; 20:00-21:00` |
| `number.*` | hőmérsékletek, küszöbök, percek, áramár |
| `binary_sensor.*_szelloztetni_kell` | saját értesítéshez / szellőzőventilátorhoz |
| `sensor.*_torolkozo_energia_ma/e_heten/e_honapban/iden/osszesen` | kWh |
| `sensor.*_torolkozo_koltseg_…` | Ft |
| `sensor.*_kovetkezo_furdes`, `*_elofutes_kezdete` | időbélyeg |

**Ötlet:** ha van **elszívó ventilátorod**, egy egyszerű automatizálással kapcsold a `binary_sensor.*_szelloztetni_kell` alapján, így értesítés helyett magától szellőztet.

---

## Üzemmódok
- **Automatikus:** órarend + előfűtés + minden törölköző szabály. Ajánlott.
- **Komfort:** folyamatosan fürdési hőmérséklet.
- **Takarékos:** folyamatosan takarékos hőmérséklet.
- **Távol:** csak fagy- és penészvédelmi minimum (17 °C). A törölköző csak akku-többletből megy.
- **Ki:** egyszer kikapcsol mindent, utána nem nyúl semmihez (kézi vezérlés). Az értesítések továbbra is működnek.
