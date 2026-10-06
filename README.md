# 🍭 Lolipop

Le radar de stages d'Andrea (EDHEC, Master in Finance, promo 2029). Il surveille **toutes les 15 minutes** les sites carrières de ~245 banques, boutiques M&A, fonds de PE / dette privée et investisseurs institutionnels, plus **LinkedIn, JobTeaser et Welcome to the Jungle**. Il t'envoie une notification Telegram dès qu'une offre qui te correspond est publiée.

À l'origine, c'est un fork de « Radar Stages ».

- 🎯 **Pour toi** : seules les offres qui collent à tes critères (`config.json` → `targets`) déclenchent une notification immédiate :
  - les **springs 2027**, partout ;
  - les **stages / off-cycle** en France, au Royaume-Uni et aux États-Unis qui démarrent entre juin et septembre 2027 ;
  - jamais une offre non éligible pour ton profil.
- 🔥 **Notification instantanée** pour chaque nouvelle offre « pour toi ».
- ☀️ **Récap à 7 h** : les nouveautés pour toi, les autres offres ciblées, les deadlines, les springs attendues et les sources en panne.
- 🌐 **Sites d'offres** : LinkedIn, JobTeaser et WTTJ couvrent les boîtes sans plateforme lisible (BNP Paribas, SG, Natixis, UBS, Tikehau, Bpifrance, boutiques…). Les doublons avec le site de la boîte sont supprimés, et les recherches se règlent dans `searches.csv`.
- 📊 **Tableau de bord** : « Pour toi », Nouveautés, Tableau, Springs 2027, Pages étudiantes, Calendrier, Candidatures et Réseau.
- 🤝 **Réseau** :
  - import de tes relations LinkedIn ;
  - suivi des contacts et relances ;
  - **carnet des boîtes** : priorité, notes libres, **deals qui t'ont marqué** reliés à tes contacts ;
  - messages prêts à envoyer, dont un modèle qui part d'un deal noté.
- ✅ **Éligibilité** : chaque offre ciblée est lue (année de diplôme, dates, langues, visa) et marquée Éligible / À vérifier / Non éligible selon `config.json` → `profile`.
- 💸 **0 €** : tourne gratuitement sur GitHub Actions.

## Installation (≈ 20 min, une seule fois)

### 1. Le bot Telegram
1. Dans Telegram, ouvre **@BotFather** (badge bleu) → `/newbot`. Donne-lui un nom (`Lolipop`) puis un identifiant qui finit par `bot` (par ex. `lolipop_andrea_bot`).
2. BotFather te donne un **token** `123456:AAH…`. Garde-le secret.
3. Ouvre ton bot et appuie sur **Démarrer**.
4. Dans le Terminal, depuis le dossier du projet :
   ```bash
   python3 -m radar telegram 123456:AAH...
   ```
   Tu reçois « ✅ Lolipop est bien connecté » et le Terminal affiche ton `TELEGRAM_CHAT_ID`.

### 2. Le dépôt GitHub
Crée un compte sur github.com, puis avec GitHub Desktop : **File → Add Local Repository** → ce dossier → **Publish repository**. Décoche « Keep this code private » : un dépôt public a des minutes illimitées et le tableau de bord gratuit. Rien de personnel n'est publié, car tes contacts et tes notes restent dans ton navigateur.

### 3. Les secrets
Sur github.com, dans le dépôt : **Settings → Secrets and variables → Actions → New repository secret** :
- `TELEGRAM_BOT_TOKEN` = ton token
- `TELEGRAM_CHAT_ID` = ton chat id

### 4. Le tableau de bord
**Settings → Pages** → Source « Deploy from a branch » → `main` / `/docs` → Save. Ton tableau de bord sera sur `https://TON-PSEUDO.github.io/lolipop/`.

### 5. Lancer
Onglet **Actions** → active les workflows → **Lolipop → Run workflow**. Deux minutes plus tard, tu reçois « 🍭 Lolipop est activé ! » avec les offres déjà ouvertes pour toi.

## Au quotidien

| Je veux… | Comment |
|---|---|
| Changer mes critères (pays, cycles, springs) | `config.json` → `targets` |
| Mettre à jour mon profil (diplôme, dates, langues) | `config.json` → `profile` |
| Ajouter / retirer une boîte | `companies.csv` (`source = manuel` = affichée mais pas scannée) |
| Ajouter une recherche LinkedIn / JobTeaser / WTTJ | une ligne dans `searches.csv` (`source,query,location`) |
| Surveiller une spring / un programme | une ligne dans `programmes.csv` |
| Surveiller une page « Students » | une ligne dans `pages.csv` |
| Changer l'heure du récap | `config.json` → `digest_hour` |
| Lancer un scan tout de suite | Actions → Lolipop → Run workflow |
| Tester en local | `python3 -m radar test` ou `python3 -m radar test Lazard KKR` |
| Lancer les tests | `python3 -m unittest discover -s tests -t .` |

**Ciblée (A)** = stage, spring ou off-cycle en M&A, IB, PE, dette privée, restructuring, ECM/DCM, infra, immobilier… ou tout stage « métier » chez une boutique ou un fonds. **Pour toi** = offre ciblée qui respecte aussi tes critères `targets` et ton éligibilité. **Autre (B)** = stage hors cible : visible dans le tableau de bord, jamais notifié.

## Tes données perso (réseau, carnet, candidatures)
Elles sont enregistrées **dans ton navigateur**, jamais sur GitHub. Pour les passer sur ton téléphone ou les sauvegarder : **Infos générales → Exporter**, puis **Importer** sur l'autre appareil. Exporte régulièrement.

## Comment ça marche
- `radar/sources.py` lit les plateformes de recrutement : Workday, Oracle, Greenhouse, Lever, Oleeo, SmartRecruiters, Recruitee, Teamtailor, Ashby, Pinpoint, Workable…, les API de Goldman Sachs et Deutsche Bank, ainsi que LinkedIn, JobTeaser et WTTJ.
- Les sites d'offres sont interrogés au plus une fois par heure (deux heures pour JobTeaser) pour éviter les blocages.
- `radar/classify.py` décide si une offre est un stage ciblé. Les cas pièges sont couverts par `tests/test_classify.py`.
- Une offre jamais vue déclenche une notification. Une offre absente 3 scans de suite est marquée fermée ; pour LinkedIn, JobTeaser et WTTJ, c'est au bout de 10 jours sans apparaître.
- Si une boîte change de site, elle apparaît « en panne » dans le récap du matin : il suffit de corriger sa ligne dans `companies.csv` (ou de me le demander).
