# ADEPR MIS — Paruwasi ya Ruhango

Management Information System (MIS) y'umushinga w'ITORERO ry'ADEPR Paruwasi ya Ruhango (V1.13).

**Scope: Paruwasi ya Ruhango gusa — amatorero 38 nyayo.**

Iyi sisitemu ikora (V1.9 — ivyavuye muri V1.8 + ibyavuye ku babyutse):
- **Role-based access (6 roles)**: Umushumba wa Paruwasi / **Muyobozi wa Paruwasi (manager)** / Umushumba w'itorero / Ushinzwe imali w'itorero / Umuyobozi w'icyiciro/ministeur / **Umuyobozi wa zone (Zone Reader)**
- **File upload**: kwiyemeza file (facture, ifoto, certificate...) ku busabe, ku mutungo, ku member profile, no kw'abashyitsi
- **Zones**: icyiciro cyo hasi cy'itorero, gifite Zone Reader. Ibyabaye muri zone bigera hejuru (bottom-up)
- **Imitungo y'amatorero (assets)**: andikwa n'itorero, paruwasi ibona byose hamwe n'agaciro, ikaba ishobora gufata umwanzuro (decision) igamenyesha itorero
- **Umwirondoro wuzuye w'umukristo**: izina, ahatuye, indangamuntu, single/married, amashuri yize, ibo yize, certificate, diplomes + photo
- **Abashyitsi (visitors)**: umushumba w'itorero abandika (ifoto, certificate, izina, telephone, intego yigishijwe) — bikagera kuri paruwasi yose
- **Kubitanya imana (discipline)**: umushumba w'itorero/ministeur ashobora guharika umukristo/umuyobozi — bigera kuri paruwasi yemeza (confirm) cyangwa agasubiza (lift)
- **Delegation**: umushumba wa paruwasi ashobora delegatera features ziwe ku muntu (by name + reason + igihe)
- **Bottom-up monitoring (activity log)**: ibyabaye byose — guhera kuri Zone Reader kugeza kuri paruwasi — bugaragara
- **Service routing (escalation)**: ibisabye byoherejwe ku rwego rukwiye (zone → ministeur → itorero → paruwasi)
- **Parish aggregators**: paruwasi ibona abakristo mu byiciro byose, muri amatorero yose, + raporo z'amaministeur yose
- **Amaturo data flow**: umuyobozi ushinzwe imali/umushumba w'itorero abishyiramo → bikagaragara kuri Paruwasi
- **Distribution 7/2/2/89**: 7% itorero, 2% Paruwasi, 2% Ururembo, 89% HQ + 50% Abana
- **Ranking**: y'amatorero ku maturo
- **SMS broadcast** + **Raporo PDF + Excel** (hamwe n'umukono wa digital)
- **Smart search + Export + Message queue + Auto weekly email + System health**
- **Modular**: itorero rishobora kwandikwa muri form iyo ari yo yose (free-text + "Kongeramo" button)

## Ibyavuye muri V1.9 (kuvugurura by'umugwi w'ababyutse)

1. **Login ifunguye amagambo bibeshye**: placeholder yari "parish" n'amagambo yerekana konti — byose byasibwe. Ijambobanga riri nk'akato (••••••••).
2. **Navigation yujuje ibyifuzo**: back button ya browser ikora neza (hash routing). Hano hari button "Subira inyuma" mu topbar ikora ku byiciro byose — nta kugenda hagati.
3. **Notifications zigaragara**: toast zikomeye zigaragara hejuru ku ecran, hamwe n'ibyibutsa (bell) bigaragara n'umubare w'ibyo ntabizi (badge). Igikorwa cyose gifite toast.
4. **Responsive mobile + tablet**: media queries z'ugushusho (mobile < 640px, tablet 640-1024px). Ibintu byoroshe gukoresha ku ya telefoni.
5. **Reports generation ikomeye**: raporo PDF + Excel kuri paruwasi yose (weekly/monthly/yearly) + raporo z'ibyiciro byose (members, churches, offerings, visitors, discipline, delegations, ministries, assets, schedules, service_requests, death_reports, users, message_queue, activity_log).
6. **Export ku bice byose**: buri paji ifite button ya Excel + PDF — nta kwandika (keyword) irimo ahatabayeho.

## Ibyavuye muri V1.10 (kwemeza amaturo ya MoMo na Bank)

1. **Ibyemezo kuri buri cyiciro**: muri form yo kwandika amaturo, buri cyiciro (Icyacumi-MoMo, Icyacumi-Bank, Amaturo...) gifite uwutubiko wa file. Umuyobozi ushinzwe imali cyangwa umushumba w'itorero afata ifoto ya **SMS ya MoMo** cyangwa **bank slip** ayishyire ku murongo wa wo.
2. **Kwibutsa ko nta cyemezo**: iyo MoMo cyangwa Bank bifite amafaranga ariko nta file yoherejwe, sisitemu ibwira ukuntu (nta kwemeza bisaba — ni kwibutsa gusa; kanda "Bika" nanone kwemeza).
3. **Paruwasi ibibona byose**: kuri paji y'amaturo (Umushumba wa Paruwasi), habaye inkingi nshya "IBYEMEZO" yerekana umubare wa file zoherejwe kuri buri cyumweru, n'agatsiko "Ibyemezo" gafungura urutonde rw'ibyemezo byose — rutoranywa ukurikije ubwoko (MoMo / Bank / ibindi), ruva mu matorero yose.
4. **Reba file ku byiciro**: muri "Items" modal (iyerekana amaturo ku byiciro), buri cyiciro kigaragaza ibyemezo byaryo, umushumba akabona ko ako kanda.
5. **API nshya**: `GET /api/offerings/attachments` (Paruwasi gusa) — urutonde rw'ibyemezo byose, rwakwiriye gufilter na `?church_id=`, `?start_date=`, `?end_date=`, `?kind=momo_sms|bank_slip|other`.

Ibyemezo bibitse kuri buri "offering item" (muri `offerings_items.json`), muri `attachments: [{path, original_name, kind, size, uploaded_at}]`. File nyakuri ziruri mu bubiko busanzwe bwa `/uploads/` (bwa `/api/upload`).

## Ibyavuye muri V1.11 (kuvugura ububiko bwa credentials)

Intego: **nta ijambobanga cyangwa igisubizo cy'umutekano kibitswe mu mvarine (plaintext)** muri `users.json`.

1. **Hashing y'ijambobanga**: buri ijambobanga rihindurwa hash ikoresheje **PBKDF2-HMAC-SHA256** (200,000 iterations, salt nsenga ku buri konti) — biturutse muri Python stdlib (`hashlib` + `hmac` + `secrets`), nta dependency nshya yongereewe. Ibizibitse biri mu field `password_hash`, mu bigeze `pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>` (bigaragara, bityo iteracyo rishobora kwiyongera guhitamo nyuma).
2. **Hashing y'igisubizo cy'umutekano**: field `security_answer` yahinduwe `security_answer_hash` ikoresheje gahunda imwe (byanditswe n'intokeye nkeya — `strip().lower()` — kugira ngo verifications zikore neza).
3. **Migration ku buzima (idempotent)**: iyo app itangiye, `_migrate_legacy_credentials()` ishaka konti zose zifite field ya kera `password`/`security_answer` (muri plaintext), zihindure hash, zikuraho field ya kera. Nta kintu kibangamira — konti zanditswe na V1.10 n'ambere zikomeza gukora n'ijambobanga ryazo. Test iri muri `scripts/test_credentials.py` yemeza ko migration ikora, idahindura ibyinshi (idempotent), kandi idasubirana hashing.
4. **Kubika kw'API**: API endpoints zose zihita zisiba fields zose z'umubanga (`password`, `password_hash`, `password_algo`, `security_answer`, `security_answer_hash`) — biturutse ku `db.SECRET_FIELDS`. Test yemeza ko `/api/users`, `/api/auth/me`, na `/api/users/pending` byose bitagaragaza na kimwe.
5. **Flow zose zikomeje gukora**: login, register, forgot-password (reset via security answer), change-password — byose bikoze neza hash hashing; API contract ntiyahindutse (abakoresha bakomeza kohereza plaintext, server ni wo uyihindura hash).
6. **Bug yari isanzwe iracyayo**: hari route ebyiri zari zisangiye urubingo `/api/auth/forgot-password`; imwe yari "dead code" yagaragazaga ko "ijambobanga ryasimburiwe" ariko ntiyari risimburura. Iyo nshuro ya kabiri yarasibwe, none route nyayo (ihamye ryo kongera ijambobanga hashize security answer) ni yo ikora.

**Test**: `python3 scripts/test_credentials.py` (44/44 ikora). Reba kandi `scripts/test_offering_attachments.py` (V1.10) na `mis/test_smoke.py` (V1.9 regression) — byose bikoze neza.

## Ibyavuye muri V1.12 (gukora restructuring y'imiterere + Gusaba kwakirwa + settings reflection)

Intego ntuntu: **gutuma sisitemu ikora modular** (kongeramo component imwe n'ingendo nkeya), **menus zikoranwa ku buri role zitagira code ibanze**, no **gusaba kwakirwa umukristo mushya gifite Parish override**.

### A. Gusaba kwakirwa umukristu — Parish override (head of all)
Hari feature yari isanzweho (`service_requests`) ariko none **Paruwasi ishobora guhana icyemezo cyafashwe na local church**:
1. Local church (umushumba/ushinzwe imali/ministeur) yasaba kwakira umukristu mushya, yerekana impamvu + file (ID, certificate).
2. Umushumba w'itorero (**CHURCH_PASTOR**) wemeza → umukristu akongerwamo mu bakristo b'itorero (auto-created, `category=ABAKRISTO_BASHYA`).
3. **PARISH_PASTOR (head of all)** ashobora **gusoma ibyangiritse + guhana icyemezo** — ikoze:
   - Status ihinduka `parish_rejected` (ntibyongera kuba `approved`).
   - Umukristu wongewemo **akuwe mu bakristo** (member `active=False`, `parish_override=True`).
   - Itorero kimenyeshwa (notification `ALL_CHURCH` + impamvu).
   - Gusa icyemezo **cyemejwe** n'itorero gishobora guhanwa (pending/rejected ntibyemewe — ibyo ni iby'itorero).
- Route nshya: `POST /api/service-requests/<id>/parish-override` (`@require_parish`).
- UI: buto "Paruwasi ihane" (igaragara kuri PARISH_PASTOR gusa ku byemejwe), status nshya "Paruwasi yahanye", impamvu + uwayihanuye bigaragara.

### B. Modular menu config (no hardcoded nav)
**Byanze:** sidebar yari hardcoded 4 `<template x-if>` blocks (parish/church/ministry/zone) — guhindura item imwe bisabaga guhindura code 4. None None None None:
- File nshya: **`menu_config.py`** — registry imwe y'ibice (COMPONENTS: icon+label+badge) + MENU_BY_ROLE (urutonde rw'ibice ku buri role) + `menu_for_role()`.
- **Burya role ifite menu yayo yegereye** — PARISH_PASTOR (25), PARISH_MANAGER (16), CHURCH_PASTOR (17), CHURCH_FINANCE (8), MINISTRY_LEADER (6), ZONE_READER (5).
- **PARISH_MANAGER ntiyibona ibyo PARISH_PASTOR yonyine** (settings, sms, delegation, abakristo bose) — bisobanuye ko manager afasha ariko ntagira uburenganzira bwa nyayo.
- **CHURCH_FINANCE afite menu y'imitima y'imali gusa** (dashboard, andika amaturo, urwego, raporo, imitungo, abashyitsi, umwirondoro, umukono) — ntiyibona Gusaba kwakirwa/Konti z'emeza (ibyo ni by'umushumba).
- Sidebar none ireba `this.menu` (array yaturutse kuri server) ikoresheje `x-for` — nta `x-if` per role iracyariho.
- **Kongeramo component nshya** = (1) yongere template, (2) yongere route, (3) yiyandike muri COMPONENTS + MENU_BY_ROLE. Ibyo byose — sidebar ikabimenya.

### C. Settings reflection muri dashboard
Hari ikibazo: sidebar header yari hardcoded "Paruwasi ya Ruhango", ntiyari ifata izina ry'ingenzi. None None None:
- Endpoint `/api/auth/session` none yohereza `parish_name`, `pastor_name`, `church_name`, `leader_name` (bivuye muri `parish_profile.json` + church record).
- Sidebar header yerekana **izina rya Paruwasi nyirizina** (biturutse kuri Settings → Parish Profile).
- Footer y'umukoresha yongeyemo **izina ry'itorero** + **izina ry'umuyobozi w'itorero** (ku bakoresha bo ku rwego rw'itorero).
- **Dashboard label y'itorero** yihariye: "Dashboard yanjye y'itorero rya RUHANGO" (izina rirahinduka ukurikije itorero cyawe).

### D. Bug na byo byafashwe
- Muri V1.11 hari route ebyiri zari zisangiye `/api/auth/forgot-password` (imwe yari dead code) — byarasibwe. None None None V1.12 ntiyahindutse.
- Typo "Seriveri yenaniranye" (yahinduwe n'amaboko) → "Seriveri yananiranye" (place 7).

**Test**: `python3 scripts/test_v12_restructure.py` (**70/70** ikora) — yemeza menu ku buri role (6 roles, harimo zoneru), reception override flow yose (submit→approve→parish-override→member deactivated→church notified→idempotent), settings reflection, na zone reader zone_id. Reba kandi V1.9 (23), V1.10 (23), V1.11 (44) — **byose 160/160 bikoze neza**.

**V1.13 test**: `python3 scripts/test_v13_per_role.py` (**35/35** ikora) — yemeza per-role features zose zisabwa muri V1.13 (zone reader register+delete-with-approval+reception, minister delete+downloads+schedule request→approve, finance MoMo+Bank+own-church reports+download, manager read-only+change-request gate+profile+download-all, parish reception-overview+SMS gateway+test+thank-you+account-approvals+escalation+name-reflection). Hamwe na V1.9 (23) + SMS gateway adoption smoke (`scripts/test_sms_gateway_adoption.py`, 11/11) → **byose 69/69 bikoze neza**.

## Ibyavuje muri V1.16 (Trilingual UI — RW/EN/FR + raporo yo kugereranya MIS)

V1.16 yongereye ibintu bibiri byasabwe n'umukoresha: (1) guhitamo ururimi (Kinyarwanda / English / Français) ku rwego rw'ikoranabuhanga ryose, (2) raporo yo kugereranya ADEPR MIS n'izindi sisiteme yo gucunga amatorero (CCB, Planning Center, Pushpay, PowerChurch, Realm) na DHIS2.

### A. Trilingual UI (RW/EN/FR)
**Icyifuzo cyari**: sisitemu yari mu Kinyarwanda gusa — abakoresha b'andi mavenze (English/French) batagisobanukirwa. **Icyifuzo none**: i18n infrastructure yubatswe kuri client-side (Alpine.js):
- **State**: `lang: (localStorage.getItem('mis_lang') || 'rw')` — ururuki rwa default ni Kinyarwanda, rwakomeje muri localStorage (rwakomeje nyuma yo gufungura cyangwa kwinjira).
- **Helper methods**: `t(key)` (translate + fallback ku key), `setLang(lang)` (hindura + bika), `roleLabelT()` (translate role label), `groupLabel(title)` (translate nav group divider), `menuLabel(item)` (translate nav item label ku page-key).
- **Translations object**: 3 indimi (rw/en/fr), buri imwe ifite ~70 keys (login, common buttons save/cancel/delete/edit, roles 6, nav groups 14, page titles 41, schedule form fields, offering proof).
- **Switcher UI**: kuri login card (3 buttons: Kinyarwanda/English/Français, accent ku rwuri) + kuri top bar (3 buttons ntoya: RW/EN/FR, accent ku rwuri).
- **Live reactivity**: nav labels, page titles, role badges, group dividers, login form, schedule edit modal, offering proof badges, toast messages — byose bahinduka ako kanya iyo uhinduye ururuki (Alpine reactivity).
- **Browser-verified**: login page (RW → EN → FR), dashboard nav (EN sidebar: OVERVIEW/CHURCHES & LEADERS/OFFERINGS & FINANCE/...; FR sidebar: APERÇU/ÉGLISES & LEADERS/...).

### B. Raporo yo kugereranya MIS (PDF)
**Icyifuzo**: umukoresha yabajije "reba system iko ikora ugereranye n'izindi MIS, umbwire ibiburamo". **Icyifuzo none**: raporo ya PDF (9 paji) yanditswe muri ReportLab + palette.cascade:
- **Section 1**: Introduction (ikimenyetso cy'iyi raporo).
- **Section 2**: ADEPR MIS feature inventory — table y'ibice 41 byose, byungirtswemo ibyiciro 9 (Imiterere, Amatorero n'Abayobozi, Amaturo n'Imali, Abakristo n'Ubufatanye, Ubutumwa, Gahunda n'Imitungo, Ministeur, Raporo, Sisitemu).
- **Section 3**: Sisiteme 6 zegereranyijwe (CCB, Planning Center, Pushpay, PowerChurch, Realm, DHIS2) — type, deployment, audience, headline modules.
- **Section 4**: Feature-by-feature comparison table (ibice 25) — ADEPR MIS n'izindi 6, ifite color-coded Yes/Partial/No, ADEPR column highlight.
- **Section 5**: ADEPR MIS strengths (ibikomeye 6: parish-over-churches hierarchy, offering proof files, 7/2/89 split, trilingual UI, offline-first open source, parish-specific workflows).
- **Section 6**: Gaps (ibyabura 7: child check-in, online giving, fund accounting/payroll, member self-service, email, data analytics, backup/concurrency).
- **Section 7**: Recommendation (priority roadmap: MoMo payment link, email broadcast, member portal, child check-in, SQLite migration).
- **QA**: pdf_qa PASS (11/11 checks), 9 paji, fonts embedded (NotoSerifSC), table centering OK.
- **File**: `ADEPR_MIS_Comparison_Report.pdf` (54 KB).

### C. Test + verify
- V1.16 i18n ntiyagize ingaruka ku masuti ya V1.15 → V1.9: V1.15 (40/40), V1.14 (27/27), V1.13 (44/44), V1.9 smoke (23/23), thank-you builder (39/39) — **byose 321/321 bikoze neza**.
- Browser-verified: login + dashboard + sidebar mu ndimi 3 (RW/EN/FR).

### D. Uburyo bwo guhitamo ururuki (final)
1. Kuri login card: kanda "Kinyarwanda" / "English" / "Français" mbere yo kwinjira.
2. Cyangwa kuri top bar: kanda "RW" / "EN" / "FR" mu gihe uri muri sisitemu.
3. Ururuki rwakomeje muri localStorage — uruhurira gukomeza kw'ururuki ku gihe cyose ushize.

## Ibyavuje muri V1.15 (FINAL — login auto-seed, menu y'ibice, ministeur edit/delete, offering proof)

V1.15 ni "final version" y'icyifuzo cy'umukoresha: (1) kugira ko login ikore ku matizaro mashya nta kintu nakora, (2) menu y'ibice (function-based) kugira ngo buri rwego rube rureba ibyifuzo byaryo gusa, (3) ministeur ashobora guhindura/kuraho ibyo yashyizeho, (4) amaturo afite proof (screenshot/slip) kuri buri maturo, agaragara kuri paruwasi.

### A. Login auto-seed (ku matizaro mashya)
**Icyifuzo cyari**: umukoresha yohereza zip, atangiza `app.py`, login yemera benshi kuko `users.json` ari ubusa. Bisabaga ko arangiza `python3 seed.py` n'intoki. **Icyifuzo none**: `app.py` mu `if __name__ == "__main__"` block, hakorwa check — niba `db.list_users()` ari ubusa, `import seed; seed.main()` ikora demo data yose (84 users, 37 churches, 8 weeks y'amaturo, ministries, etc.) hanyuma app itangire. seed.py idempotent (ikora `find_user_by_username` mbere yo kongeramo), nta kibazo cyo gusubiramo. Ibyifuzo: umukoresha yohereza zip → atangiza `app.py` → yinjira na `parish/parish123` byahoze.

### B. Menu y'ibice (function-based grouping)
**Icyifuzo cyari**: sidebar yari urutonde rw'ibintu 20-30 (parish pastor) rweruruye, nta cyiciro. **Icyifuzo none**: `menu_config.py` `MENU_BY_ROLE` yahindutse ku bwoko bw'ibice — buri rwego rufite list ya `{"title": "Izina ry'icyiciro", "items": [...]}`. Ibyiciro bya parish pastor: Imiterere, Amatorero n'Abayobozi, Amaturo n'Imali, Abakristo n'Ubufatanye, Ubutumwa (SMS), Gahunda n'Imitungo, Raporo, Sisitemu. Ibyiciro bya ministeur: Imiterere, Ministeur yanjye, Abakristo, Gahunda, Raporo, Konti n'Umwirondoro. Template ifite divider (small caps, muted) ku kubanza kw'icyiciro cyose — sidebar imeze nk'amazina y'ibiciro, si urutonde rurerure. Buri rwego rureba ibyifuzo byaryo gusa (per-role filtering yari isanzweho).

### C. Ministeur edit/delete ibyo yashyizeho
**Icyifuzo cyari**: ministeur ashoboraga gusa guhindura ibintu (schedules, service requests) ariko ntiyabishoboraga guhindura/kuraho. **Icyifuzo none**:
- **Schedules**: `PUT /api/schedules/<id>` (hindura title/description/datetime/location) + `DELETE /api/schedules/<id>` (kuraho). Ownership check: `scheduled_by == user.id` cyangwa parish pastor. UI: kuri schedule card, "Hindura" + "Kuraho" buttons zerekana kuri owner gusa (modal ya edit ifite title/desc/datetime/location fields).
- **Service requests**: `POST /api/service-requests/<id>/withdraw` (kuraho gusaba kwawe niba kikiri pending). Ownership check: `requester_id == user.id`. Status ikaba "rejected" n'ikimenyetso "[WITHDRAWN by requester]".
- **DB**: `db.update_schedule()` + `db.delete_schedule()` nshya (update_schedule_status yari isanzweho).

### D. Offering proof (file upload per offering, visible at parish)
**Icyifuzo cyari**: file input yari isanzweho ku buntu (MoMo/Bank) ariko nta mwanya wo kwemeza — warashoboraga kubika nta cyemezo. **Icyifuzo none**:
- **Enforce**: igihe hari MoMo/Bank bifite agaciro ariko nta cyemezo, save irahagarara. Confirm dialog: "Urabyemera kubika nta cyemezo?" — niba yemera, bika bifite ibendera `no_proof: true` (parish auditor arabibona); niba yanze, garuka kongera icyemezo.
- **Attach-after-save**: `POST /api/my-offerings/items/<item_id>/attachments` — ushobora kwongeramo icyemezo kuri offering yabaye (slip yahise igera nyuma). Ownership: church pastor/finance w'itorero ryayo cyangwa parish. Ibyifuzo: item ikaba `no_proof: false` (clear) hanyuma attachment igera.
- **Parish visibility**: kuri parish offerings table, "IBYEMEZO" column ifite badge y'icyemezo (emerald, count) + badge ya "NTA CYEMEZO" (red, count y'ibintu byafite `no_proof`). Item view modal ifite "Ongerako icyemezo" button (church/parish) + "Nta cyemezo (MoMo/Bank)" badge kuri buri kintu.
- **DB**: `offerings_items` row yongeyeho `no_proof: bool` (default false). `db.insert_offering()` iracyakira `no_proof` kuri buri kintu.

### E. API endpoints nshya/zahinduwe (V1.15)
- `PUT /api/schedules/<id>` — **nshya**: edit schedule (ownership: creator cyangwa parish).
- `DELETE /api/schedules/<id>` — **nshya**: delete schedule (ownership: creator cyangwa parish).
- `POST /api/service-requests/<id>/withdraw` — **nshya**: withdraw own pending request.
- `POST /api/my-offerings/items/<item_id>/attachments` — **nshya**: attach proof to a saved offering item (ownership: church finance/pastor cyangwa parish).
- `GET /api/auth/session` — menu items zongeyeho `group` field (izina ry'icyiciro).

### F. Test
- `scripts/test_v15_final.py` (40/40): FEATURE 1 (login konti 5 zose: parish, manager, ruhango, ruhango_fin, leader_abana), FEATURE 2 (buri rwego rufite ≥3 groups + buri kintu gifite group field + V1.14 carryover sms_gateway/thank_you_sms), FEATURE 3 (ministeur create/edit/delete schedule, non-owner 403, parish oversight, service-request withdraw + ownership), FEATURE 4 (offering no_proof=True save, parish visibility, upload + attach-after-save, no_proof clear, non-owner 403).
- Hamwe na V1.9 (23) + V1.10 (23) + V1.11 (44) + V1.12 (70) + V1.13 (44) + V1.14 (27) + SMS adoption (11) + thank-you builder (39) + V1.15 (40) → **byose 321/321 bikoze neza**.

### G. Uburyo bwo gukoresha (final)
1. Hunzina zip → `unzip ADEPR_MIS_FINAL.zip` → `cd ADEPR_MIS_V9/mis`
2. `pip install -r requirements.txt`
3. `python3 app.py` — app ihita yaseed demo data (84 users) ku matizaro mashya, scheduler itangira, login ikora.
4. Kwinjira: `parish / parish123` (cyangwa `ruhango / church123`, `leader_abana / leader123`, `ruhango_fin / finance123`, `manager / manager123`).
5. Sidebar: ibice bya function (Imiterere, Amaturo n'Imali, etc.) — buri rwego rureba ibyaryo.
6. Ministeur: reba schedule, kanda "Hindura" cyangwa "Kuraho" ku byo washyizeho.
7. Church finance: andika amaturo → MoMo/Bank igomba gufite proof (cyangwa wemeje nta cyemezo, bityo badge "NTA CYEMEZO" igaragara kuri parish). Niba slip yahise igera nyuma, kanda "Ongerako icyemezo" kuri item.
8. Parish: reba offerings table — badge y'ibyemezo + badge ya "NTA CYEMEZO" kuri buri maturo.

## Ibyavuje muri V1.14 (thank-you SMS: message yahinduka, custom contacts, auto-send queue)

V1.13.2 yatanze builder ya message2.py-style; V1.14 yongeyeho ibintu bitatu by'ingenzi byasabwe n'umukoresha: (1) ubutumwa bushobora guhindurwa, (2) contact zitari muri list zishobora kwongerwa, (3) auto-mode — iyo gateway ihuye, message zose zari mu queue zihita ziyohereza ntizisaba ko mukuri.

### A. Customizable message (modal textarea + Reset)
Mbere: modal yari "preview" gusa (nta cyo wahinduraga). Noneho: modal ifite `<textarea>` ahubwo ya `<pre>` — parish pastor ashobora guhindura message ku giti cye mbere yo kohereza (ex: gukombya amazina, kongeraho ibitekerezo, kuvugurura umubare). "Reset" yongera message2.py template (kuvoma kuri builder). Iyo user atarahinduye (edited=false), POST ihereje `message: ''` — builder ikora message ku rubuga (nziza cyane kuruta kwimakaza inyandiko). Iyo user yahinduye (edited=true), message yahinduwe iherekeza.

### B. Custom contacts (extra_contacts)
Mbere: message yoherezwaga umuyobozi w'itorero gusa (recipient_phone imwe). Noneho: modal ifite "contacts editor" — urutonde rw'imirongo `{izina, telefone}`, ufite "Ongerako Kontakt" + "×" (kuraho). Umuyobozi ashyirwa ku murongo wa mbere (akomoka kuri leader_phone); parish pastor ashobora kongeremo abandi bantu badahari ku rutonde (ex: pasteur wungirije, ushinzwe imali, umubyeyi w'inama). POST yemera `extra_contacts: [{name, phone}, ...]`; backend ikora `sms.broadcast()` ku bantu bose mu rugendo rumwe, hanyuma andike log imwe kuri buri muntu (kugirango panel yerekane delivery ya buri telefone).

### C. Auto-send queue (auto_send_enabled + scheduler)
Ibi ni "anytime gateway ibaye connected, message ziyohereza automatically":
- **Toggle**: kuri panel "SMS Gateway", hafi ya "Dry-run" checkbox, hari "Auto-send" checkbox. Default OFF — nta kintu gikora n'agatapatano.
- **Scheduler**: APScheduler (yari isanzweho) yongeyeho job `process_thank_you_queue` ikora buri minota 2. Job ikora:
  - Iteeka `db_v13.list_pending_thank_you_sms()` — message zose zifite status='dry_run' cyangwa 'queued'.
  - Iteeka ko `auto_send_enabled=True` AND `dry_run=False` AND endpoint iriho (gateway live). Aha ni ho "gateway ihuye" huzuye.
  - Buri murongo: `sms.send_one_sms(phone, message, dry_run=False)` → niba byagenze neza, status='sent' + sent_at + attempts+1. Niba byanze, attempts+1; ku cyiciro cya 5 gikomeye, status='failed'.
- **Immediate trigger**: kugira ngo ntibehere kuminota 2, scheduler ikora na:
  - Iyo parish pastor adutuye "Bika" kuri gateway config (auto_send ON + live) → queue ihita ikora.
  - Iyo "Tumiza test" igera kuri 200 (gateway ihuye) → queue ihita ikora.
  - Iyo POST `/api/thank-you-sms` ikora dry_run (gateway ntikora) ariko auto_send ON → queue ihita ikora (bityo message ikwandika na none, na dry_run ikaba na sent muri make).
- **Manual drain**: "Kohereza None" (boto kuri panel) cyangwa POST `/api/thank-you-sms/queue/drain` — bikora queue n'intoki nta kuguma.

### D. API endpoints nshya/zahinduwe
- `POST /api/thank-you-sms` — yemera `extra_contacts: [{name, phone}]`; koresha `sms.broadcast()` (si `send_one_sms`); log imwe kuri buri receptor.
- `GET /api/thank-you-sms/preview` — (V1.13.2) udahindutse.
- `GET /api/thank-you-sms/queue` — **nshya**: count, auto_send_enabled, gateway_live, next_tick_in_sec, + list ya pending.
- `POST /api/thank-you-sms/queue/drain` — **nshya**: manual trigger ya queue processor.
- `PUT /api/sms-gateway` — noneho yemera `auto_send_enabled` (whitelist yongeyeho); iyo config ihinduka ikaba live + auto ON, queue ihita ikora.
- `POST /api/sms-gateway/test` — iyo test iganisha 200 + auto_send ON, queue ihita ikora.

### E. DB schema (`db_v13.py`)
- `_DEFAULT_GATEWAY` yongeyeho `auto_send_enabled: False`; whitelist yongeyeho ikindi kintu; bool normalization.
- `insert_thank_you_sms` yongeyeho `extra_contacts: []`, `queued_at`, `sent_at`, `attempts: 0`.
- `update_thank_you_sms(rec_id, updates)` — **nshya**: patch imwe muri row (ikomoka kuri scheduler + manual re-send).
- `list_pending_thank_you_sms(limit=200)` — **nshya**: rows zifite status in ('queued','dry_run'), by order ya queued_at.

### F. Scheduler (`scheduler.py`)
- `process_thank_you_queue()` — **nshya**: drain queue, gating logic (auto_send + live gateway), retry cap (5 attempts → failed), per-row update.
- `start()` yongeyeho job: `s.add_job(process_thank_you_queue, "interval", minutes=2, id="thank_you_auto")`.
- Fallback loop (na APScheduler itabahoze) yongeyeho kandi ikora queue.

### G. UI
- **Modal ya thank-you**: textarea yahinduye pre; "Reset" yongera template; contacts editor (ongerako/kuraho); meta summary; warning niba data itabonetse; boto "Tumiza" + "Vugurura" + "Funga".
- **Panel "SMS Gateway"**: "Auto-send" checkbox hafi ya "Dry-run"; badge eratana "Ubutumwa buri mu queue: N" + "auto ON/OFF"; boto "Kohereza None" (manual drain).
- **Panel "Ubutumwa bwo gushimira"**: message zerekanwa na `whitespace-pre-line` (multiline); status badge (sent/dry_run/failed); per-receptor row.

### H. Test
- `scripts/test_v14_thank_you_queue.py` (27/27): FEATURE 1 (custom message stored as-is), FEATURE 2 (extra_contacts → 4 rows muri log, IMIBARE section in default), FEATURE 3 (queue endpoint, gating logic — auto OFF/dry_run=True/no endpoint zose ziranga), queue processing monkeypatched (dry_run → sent, sent_at, attempts+1).
- Hamwe na V1.9 (23) + V1.10 (23) + V1.11 (44) + V1.12 (70) + V1.13 (44) + SMS adoption (11) + thank-you builder (39) + V1.14 (27) → **byose 281/281 bikoze neza**.

## Ibyavuje muri V1.13 (per-role features zisabwa)

### A. Kurwego rwa zone (Zone Reader)
- **Kwandika umukristo mushya**: zone reader ashobora kwiyandikisha umukristo mushya muri zone ye (menu: "Abakristo b'iyi zone").
- **Gusaba gukuramo umukristo (delete-with-approval)**: zone reader ntabwo ashobora gukuraho umukristo yonyine — asaba (na `deletion_requests`), ashyiraho **impamvu + umukono we** (signature canvas). Umushumba w'itorero wemeza cyangwa aranga. Iyo wemejwe, umukristo **aburirwaho ku rutonde** (active=False) ariko amateka yakomeza (amateka y'amaturo n'ibindi).
- **Gusaba kwakirwa (reception request)**: zone reader asaba kwakira umukristu — bisorowa ku rwego rw'itorero (ntibigera ku mushumba wa paruwasi).
- **Izina ry'itorero na zone**: byagaragara kuri dashboard ya zone reader (church_name + zone name).

### B. Umuyobozi wa ministeur (Ministry Leader)
- **Gusaba gukuramo umukristo**: nkimwanya wa zone — minister asaba (na reason + signature), umushumba w'itorero wemeza.
- **Download (Excel/PDF)**: minister ashobora gukora download y'amakuru ye (members, offerings) muri Excel na PDF.
- **Gahunda (event scheduling)**: minister asaba gahunda nshya (na `category`: Abana/Urubyerero/Ibyishimo/...). Umushumba w'itorero yemeza cyangwa aranga agatanga undi gihe (plan ya church). Status: `pending → approved / declined`.

### C. Ushinzwe imali (Finance Manager)
- **Form y'amaturo**: hagombayo kwemerera kw'iyandikwa rya **screenshot ya MoMo** + **foto ya bank slip** (per category — ICYACUMI_MOMO, ICYACUMI_BANK). Ibi bisanzwe biri muri offering form (file upload per category).
- **Amazina ajyane n'ibyo tugiye gukora**: offering categories zisobanwe neza (offering, not gift; ranking, not hierarchy). Ijambo "gift" cyangwa "church hierarchy" nta n'rimwe riri muri code (byemejwe na grep).
- **Raporo**: finance abona **iyitorero rye gusa** (own-church offerings), ashobora gukora download y'amaturo n'abakristo. Report yatanze umushumba ayibone nawe (finance n'umushumba bahuriye ku makuru y'itorero).

### D. Muyobozi wa paruwasi (Parish Operations Coordinator / Manager)
- **Read-only**: manager abona ibiri muri panel yiwe (churches, pastors, ministries, offerings, budgets, rankings, reports, ...), ariko **ntabwo ashobora guhindura** atari uko umushumba wa paruwasi amuhaye uburenganzira (delegation).
- **Change-request gate**: iyo managerifuza guhindura (create/update/delete) atafite delegation, igikorwa cye kihita kiba **change request** (`manager_changes` panel). Umushumba wa paruwasi wemeza → change ikorwa (replay against real db function). Probe endpoint: `/api/change-requests/probe`.
- **Settings yiwe**: manager afite `my_settings` (profile edit — name/phone/email/photo), bihita bigaragara kuri dashboard.
- **Download y'amakuru yose**: manager ashobora gukora download muri Excel/PDF mubyiciro byose (churches, members, offerings, ...).

### F. Kurwego rw'umushumba wa paruwasi (Parish Pastor)
- **Delegation**: umushumba wa paruwasi ashobora guha manager uburenganzira bwo guhindura feature runaka (`delegations` — feature field), cyangwa kwambura.
- **Reception overview**: `reception_overview` panel — urutonde rw'abasabwe (pending), abemejwe (approved), n'abatse (baptized) buri torero. Gusaba kwakirwa ntigushobora kugera hano (bikorwa ku rwego rw'itorero); ahubwo haza list y'ibyo status.
- **Death certificate**: umukristo wapfuye arimo kuri `death_reports`; certificate ishobora gukurwamo (member yasibiwaho active=True None None None — actually deactivated; details muri death_reports panel).
- **Igihembo cy'amatorero (events by category)**: schedules zishobora kugabanyijwamo category (Abana, Urubyerero, Ibyishimo, ...) — `schedule_requests` panel.
- **SMS Gateway (Tracar)**: `sms_gateway` panel — configuration ya Tracar SMS Gateway (endpoint, token, sender_id, phone, app). Hano niho dukorera configuration + **test** y'uko message ishobora kugenda (local tokens + endpoint). Default ni dry_run (nta message igenda). Iyi configuration ni yo yakoze: `sms.py` isoma endpoint/token/dry_run muri panel mbere (hanyuma muri env vars `SMS_GATEWAY_URL` / `SMS_GATEWAY_TOKEN` / `SMS_DRY_RUN`, hanyuma muri default `http://192.168.1.169:8082`), bityo ukwishyira kwiyandikisha muri panel bigira ingaruka ku nyigisho zose — broadcast, thank-you SMS, n'amakuru y'amaturo yageze. **Test** y'uko message igenda ikoze mu nzira imwe y'amakuru y'ahandi (`sms.send_one_sms()`): test iganisha 200 = message izagenda mu bihe by'ukuri. Pattern yo kohereza (ku moko y'inyandiko ya reference): `POST {endpoint}/send-sms` form-encoded `{phone, message}` hamwe na header `Authorization: Bearer {token}`; telefone zikomezwamo hakoreshejwe `normalize_phone()` (0788…, +250788…, 250788… → 0788123456).
- **Konti z'emeza**: umuyobozi w'itorero agomba kwemezwa numushumba wa paruwasi nyuma yokureba umwirondoro we (harimo na profile picture) — `pending_users` panel.
- **Ubutumwa bwo gushimira (thank-you SMS)**: `thank_you_sms` panel — buri torero rihabwa ubutumwa bwo gushimira ku maturo ryatanzwe mu cyumweru runaka, bukohererezwa muri SMS hakoreshejwe Tracar gateway yagenwe.
- **Escalation + delegation**: umushumba wa paruwasi ashobora gukuyejurura isabye ryo kwakira (escalate) akagishyira ku maboko wundi muntu (delegate) n'feedback. None None None None ibibazo byihutirwa bivuye ku muyobozi w'itorero, umushumba wa paruwasi akagira icyo abikoraho.
- **Izina ry'umushumba ribonera kuri dashboard + umwirondoro we**: izina na phone ya parish pastor bihinduka muri settings (my_settings), bihita bigaragara kuri dashboard n'andi maso (session refresh).

## Ibyavuje muri V1.13.2 (thank-you SMS yuzuye — message2.py-style)

Hafi y'uko V1.13 itanga "thank-you SMS" y'umurongo umwe gusa (`"Murakoze {church} kw'amaturo… Imana ibahe umugisha."`), V1.13.2 yongeyeho builder y'ubutumwa bwa message2.py-style — yuzuye n'imibare yose, ranking mu karere, ijanisha, n'umugisha. Template y'umwerere y'umukoresha yatoragurwe nta cyo byahinduwe; gusa amazina y'aba columns yahinduwe agoresheje data ya MIS.

### A. Builder nshya: `thank_you_message.py`
Module nshya ikora ubutumwa bwa message2.py template ikomoka kuri `db.rankings(start_date=week_date, end_date=week_date)` — nta pandas, nta sheets_reader. Mapping ya columns (message2.py → MIS):
- `AMAZINA` → `leader_name` (izina ry'umuyobozi w'itorero)
- `ITORERO` → `name`
- `AMATURO YOSE` → `igiteranyo` (gross total)
- `MOMO AMOUNT` → `icyacumi_momo`
- `BANK AMOUNT` → `icyacumi_bank`
- `ASIGARA (7%)` → `church_7` (RATE_CHURCH_7 = 0.07)
- `AKOMEZA (kuri paruwasi)` → `parish_2` (RATE_PARISH_2 = 0.02)
- `RANKING` → `rank`
- `TELEPHONE` → `leader_phone`

Ubutumwa bwuzuye: "Muraho {izina}, … Tubashimira cyane ku murimo mwakoze mu itorero {itorero}. Raporo yanyu yageze kuri {parish}… IMIBARE Y'AMATURO: Amaturo yose / Kuri MoMo / Kuri Banki / 7% Asigara kwitorero / Kuri Paruwasi … URUHARE MU KARERE: {akamaro} / Ijanisha {share:.1f}% / Amatorero yose {n_total} … Mukomeze muri uru rugendo rwiza, kandi Imana ibahe umugisha." Ranking label: rank 1→`UMUNYAMWANYA WA MBERE`, 2→`…WA KABIRI`, 3→`…WA GATATU`, else→`Urwego #{rank}`.

**Fallback**: iyo data itabonetse (nta offering ku cyumweru cyo, cyangwa itorero ritabonetse muri rankings), builder isubiza flat one-liner — endpoint ntigereke. `available` flag ikubiye muri response ikwiriye.

### B. POST `/api/thank-you-sms` (parish pastor/manager)
Uburyo bwa kera: message yari default hardcoded y'umurongo umwe. Noneho: niba client atahereje `message`, builder ikora message2.py-style ikomoka kuri `church_id` + `week_date`. Client ashobora gukoresha override `message` niba ashaka. Kohereza bikomeje gukorwa na `sms.send_one_sms()` (gateway) — bitizani cyangwa dry_run nka kabere.

### C. GET `/api/thank-you-sms/preview` (parish pastor/manager) — nshya
Endpoint nshya itakoherereza. Isubiza `{available, message, meta, church_id, church_name, week_date, recipient_phone, recipient_name, char_count, sms_segments}`. Ikoreshwa n'UI kugirango yerekane user message mbere yo kanda "Tumiza". `meta` ikubiyemo imibare yose (izina, itorero, amaturo, momo, bank, retenu, kuri_par, rank, share, n_total, total_amaturo, impuzandengo, ako_akamaro, uko_byagenze, parish_name).

### D. Auto thank-you ku offering insert (app.py:706) — kuvugurura
Mbere: message y'umurongo umwe `"Murakoze {church_name}! Amaturo y'icyumweru yabitswe neza: {igit:,} RWF. Imana ibahe umugisha."` + `dry_run=True` broadcast (silent). Noneho: builder ikora message2.py-style + broadcast `dry_run=True` + andika muri `thank_you_sms_log` (status='dry_run', gateway_response='auto thank-you (dry_run) — parish pastor ahitemo Tumiza') — bituma panel "Ubutumwa bwo gushimira" yerekana ko byagenze neza. Auto-trigger ikomeza kuba dry_run (nta kohereza kw'ukuri ku auto); parish pastor ahita asoma + ahitemo "Tumiza" muri panel.

### E. UI — panel "Ubutumwa bwo gushimira" + modal
- Paji "Uruhare (Ranking)": buri murongo w'itorero ufite boto 📨 → ufungura modal y'ubutumwa bwo gushimira.
- Modal: tariki y'icyumweru (default = end_date ya ranking filter) + telefone ya receptor, hanyuma preview ya message2.py-style (char count + SMS segment estimate). Reba meta (amaturo, ranking, ijanisha, amatorero yose). ⚠ warning niba data itabonetse (available=False). Boto "Vugurura" (re-fetch preview) + "Tumiza" (POST).
- Panel "Ubutumwa bwo gushimira": message zose zibitswe zerekanwa na `whitespace-pre-line` (kugirango message2.py multiline igaragare neza) + status badge (sent/dry_run/failed) + recipient_phone + timestamp. Hasi: igice cy'uburyo bwo gukoresha.

### F. Test
- `scripts/test_thank_you_message.py` (39/39): yemeza ko builder ikora message2.py template y'ukuri (greeting+name+church+IMIBARE section+URUHARE section+blessing), ko imibare ikomoka kuri `db.rankings()` (nta byo byahimbawe), ko ranking label logic ihuye, ko fallback ikora (week nta offering + bogus church_id), ko `build_flat()` ikora.
- `scripts/test_v13_per_role.py` (44/44 — byongereyeho 9): HTTP checks z'uko POST `/api/thank-you-sms` ikora message2.py-style (has "IMIBARE Y'AMATURO" + "URUHARE MU KARERE" + church name), ko status='dry_run', ko preview endpoint isubiza meta + sms_segments, ko preview fallback (bogus week) → available=False.

Hamwe na V1.9 (23) + V1.10 (23) + V1.11 (44) + V1.12 (70) + V1.13 (44) + SMS adoption (11) + thank-you builder (39) → **byose bikoze neza**.

## Ibyavuje muri V1.12.1 (kubisobanuro kw'ikibazo cyo "manager na zone ntibyinjira")

Ikibazo wabonye: account ya manager na zone ntibyemera login. Impamvu zabaye ebyiri:

1. **Data ya kera**: ufite data yakorewe na V1.9/V1.10/V1.11, hash ya password ya manager/zoneru yari itandukanye (cyangwa status yari `pending`) — V1.11 hashing byahindutse, ariko konti za kera zari zisigaye zifite hash ya kera.
2. **zoneru nta zone_id**: seed.py yari yaremuye zoneru afite church_id gusa, atagira zone_id. Ibi bituma dashboard ye ireba ubusa (kandi ikibazo cyaba gikomeye ku nzira zimwe na zimwe).

**Ibyo nakoze**:
- File nshya: **`reset_demo_accounts.py`** — script y'idempotent ivugurura konti 6 z'ibyiciro (parish, manager, ruhango, ruhango_fin, leader_abana, zoneru): hashing password nyayo + status='active' + active=True + zoneru agabana zone_id + zone igafata reader_id. **Nta kindi cyandikwa** (amaturo, abakristo, budget... byose ntibyahinduka). Ikoreshwa: `cd mis && python3 reset_demo_accounts.py`.
- **seed.py yavuguruwe**: zoneru none agabana zone_id (zone ya mbere cyangwa iyanditswe nshya) + zone igafata reader_id — data nshya ntiyongera kugira ikibazo.
- V1.12 test none yemeza login ya konti 6 zose (zoneru yongeyemo).

**Uburyo bwo gukosora data ya kera (nshyurire)**:
```bash
cd mis
python3 reset_demo_accounts.py   # konti 6 zose zikora noneho
# none None None injira:
#   parish / parish123, manager / manager123, ruhango / church123,
#   ruhango_fin / finance123, leader_abana / leader123, zoneru / zone123
```

## Tech Stack

| Layer | Tools |
|-------|-------|
| Backend | Python 3, Flask, Flask-CORS |
| Storage | JSON files (offline by default) |
| Auth | Session cookie (HttpOnly, 7-day TTL) |
| Reports | ReportLab (PDF), openpyxl (Excel) |
| SMS | HTTP gateway (optional) |
| Frontend | Single-file HTML: Tailwind CSS, Alpine.js, Chart.js, Boxicons |

## Setup

```bash
cd mis
pip install -r requirements.txt
python3 seed.py        # andika amakuru y'ibyiciro (gwa mbere gusa)
python3 app.py        # tangiza seriveri → http://127.0.0.1:5000
```

## Akonti z'ibyiciro (demo)

Iyi akonti zaremewe na `seed.py`. Hindura ijambo ry'ibanga nyuma yo kwinjira.

| Role | Username | Password | Ubusobanuro |
| --- | --- | --- | --- |
| PARISH_PASTOR | `parish` | `parish123` | Umushumba wa Paruwasi (admin wose) |
| PARISH_MANAGER | `manager` | `manager123` | Muyobozi wa Paruwasi (ubukungu) |
| CHURCH_PASTOR | `ruhango` | `church123` | Umushumba w'itorero rya Ruhango |
| CHURCH_FINANCE | `ruhango_fin` | `finance123` | Ushinzwe imali w'itorero |
| MINISTRY_LEADER | `leader_abana` | `leader123` | Umuyobozi wa ministeur y'Abana |
| ZONE_READER | `zoneru` | `zone123` | Umuyobozi wa zone |

Amazina y'andi matorero akurikiza izina ry'itorero mu nyuguti nto (urugero: `gisanga`, `kinazi`...). Konti z'imali zongeraho `_fin` (urugero: `gisanga_fin`).

Kwiyandikisha konti nshya: kanda "Kora konti nshya" kuri login page, hitamo role + itorero ryawe (cyangwa wandike izina ry'itorero rishya iitarimo). Umushumba w'itorero akemeza.

## Architecture

```
mis/
├── app.py              # Flask routes + API (V1.9)
├── db.py               # JSON storage + business logic
├── auth.py             # Sessions + RBAC (6 roles)
├── scheduler.py        # Background queue + weekly email
├── seed.py             # Demo data
├── reports.py          # ReportLab PDF + openpyxl Excel
├── helpers.py          # PDF header / footer / signature
├── requirements.txt
├── README.md
├── data/               # JSON storage (auto-created)
├── uploads/            # Uploaded files (auto-created)
├── reports/            # Generated PDF + Excel (auto-created)
└── templates/
    └── index.html      # Single-page Alpine.js UI (responsive V1.9)
```

## Roles & permissions (V1.9 — 6 roles)

Reba table yuzuye muri `ADEPR_MIS_Documentation.pdf` (Section 5). Mu rugingo:

- **PARISH_PASTOR** — admin wose, yemeza ibyemezo by'ingenzi (discipline, asset decisions, delegation)
- **PARISH_MANAGER** — ufasha paruwasi, cyane ku bukungu (amaturo, imitungo, agaciro)
- **CHURCH_PASTOR** — cuma itorero (abakristo, amaturo, imitungo, abashyitsi)
- **CHURCH_FINANCE** — andika amaturo n'imitungo y'itorero
- **MINISTRY_LEADER** — cuma icyiciro/ministeur
- **ZONE_READER** — umuyobozi wa zone, asobanura abakristo be

## Owner & acknowledgements

- **Owner**: ADEPR Paruwasi ya Ruhango
- **Version**: 1.13 (2026) — V1.9 + ibyemezo bya MoMo/Bank (V1.10) + hashing ya credentials (V1.11) + modular menus + Gusaba kwakirwa Parish override + settings reflection (V1.12) + reset_demo_accounts.py + zoneru zone_id fix (V1.12.1) + per-role features: zone/minister delete-with-approval, manager change-request gate, Tracar SMS gateway, thank-you SMS, reception overview, schedule requests, profile edit (all roles) (V1.13) + SMS gateway wiring: `sms.py` isoma configuration muri panel (`db_v13.load_sms_gateway()`) mbere y'env vars; `/api/sms-gateway/test` ikora mu nzira imwe ya production (`sms.send_one_sms()`); `scripts/test_sms_gateway_adoption.py` (V1.13.1)

Reba `ADEPR_MIS_Documentation.pdf` kubwiriza amakuru yose (ibice 4.1–4.35 + V1.9). Ibyavuye muri V1.10 na V1.11 birasobanurwa mu byiciro byo hejuru.
