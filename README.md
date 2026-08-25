# Fintra til Home Assistant

Fintra er en uofficiel Home Assistant-integration til danske ForældreIntra-sider.
Integrationen henter den aktuelle uges klasse- og SFO-planer og kan bruge nyere
beskeder til at fremhæve praktiske huskepunkter.

Integrationen er ikke udviklet, godkendt eller supporteret af itslearning eller
den enkelte skole.

## Funktioner

- Opsætning direkte i Home Assistants brugerflade.
- Valg af skole ved kun at angive skolenavnet.
- Automatisk opdagelse og valg af børn på forældrekontoen.
- Klasseplaner og separate SFO-planer.
- To sensorer pr. barn: **Dag** og **Uge**.
- Dagssensoren indeholder dags dato og næste dag.
- Ugesensoren indeholder hele den aktuelle ISO-uge.
- Valgfri analyse af beskeder fra de seneste syv dage.
- Genlogin-flow når adgangskoden ændres eller bliver afvist.
- Automatisk opdatering ved opstart og derefter én gang i døgnet.

## Krav

- Home Assistant 2025.1.0 eller nyere.
- HACS, hvis integrationen skal installeres gennem HACS.
- En aktiv ForældreIntra-konto med almindeligt brugernavn og adgangskode.

Første version understøtter almindeligt ForældreIntra-login. UNI-Login er ikke
understøttet endnu.

## Installation med HACS

Indtil Fintra eventuelt optages i HACS' standardkatalog, tilføjes repositoryet
som et brugerdefineret repository:

1. Brug repositoryadressen `https://github.com/tobiaslindgreen/fintra`.
2. Åbn **HACS** i Home Assistant.
3. Vælg menuen øverst til højre og derefter **Brugerdefinerede repositories**.
4. Indsæt URL'en til GitHub-repositoryet.
5. Vælg kategorien **Integration** og tryk **Tilføj**.
6. Find **Fintra** i HACS, vælg **Download**, og genstart Home Assistant.

Ved releases anbefales et Git-tag som `v0.1.3`, der svarer til versionen i
`custom_components/fintra/manifest.json`.

## Manuel installation

1. Kopiér mappen `custom_components/fintra` til Home Assistants
   `config/custom_components/fintra`.
2. Genstart Home Assistant.
3. Fortsæt med konfigurationen nedenfor.

## Konfiguration

Gå til **Indstillinger > Enheder og tjenester > Tilføj integration**, og søg
efter **Fintra**.

### 1. Vælg skole

I feltet **Skolenavn** skal du kun skrive den del af skolens ForældreIntra-
adresse, der står før `.m.skoleintra.dk`.

Eksempler:

```text
lyngbjerggaardskolen
```

Fintra omdanner automatisk værdien til
`lyngbjerggaardskolen.m.skoleintra.dk`. Et komplet hostname eller en fuld
HTTPS-adresse accepteres fortsat af hensyn til eksisterende opsætninger.

### 2. Log ind

Angiv det almindelige ForældreIntra-brugernavn og adgangskoden. Fintra åbner
loginformularen, medsender formularens skjulte sikkerhedsfelter, gennemfører
ForældreIntras SAML-logintrin og kontrollerer, at login ender på en gyldig
forældreside.

Adgangskoden gemmes i Home Assistants config-entry-lager på samme måde som
andre integrationers loginoplysninger. Den skrives aldrig til Fintras log.
Sessionscookies holdes adskilt pr. konfigureret konto og gemmes ikke af Fintra.

Hvis ForældreIntra beder om bekræftelse af kontaktoplysninger, skal dette først
gøres manuelt på hjemmesiden. Start derefter opsætningen igen.

### 3. Vælg børn

Efter login finder Fintra automatisk de børn, som kontoen giver adgang til.
Vælg ét eller flere børn. Der oprettes to sensorer for hvert valgt barn.

Hvis børnene senere skal ændres:

1. Åbn **Indstillinger > Enheder og tjenester > Fintra**.
2. Vælg **Konfigurer**.
3. Markér de ønskede børn og gem.

### 4. Vælg beskedberigelse

Indstillingen **Brug beskeder til vigtige huskepunkter** er aktiveret som
standard. Når den er aktiv, læser Fintra de nyeste samtaler og medtager kun
beskeder fra de seneste syv dage, der indeholder handlingssignaler som:

- husk eller medbring;
- tilmelding, svarfrist eller deadline;
- møde eller samtale;
- tur, udflugt eller transport;
- aflysning, flytning eller ændrede mødetider.

Beskeder markeres ikke som læst. Fællesbeskeder deduplikeres, men knyttes til
alle relevante børn. Hele indbakken eksponeres ikke som Home Assistant-data.

## Sensorer

For et barn med navnet Vester oprettes typisk:

- `sensor.vester_dag`
- `sensor.vester_uge`

Det endelige entity-id bestemmes af Home Assistant og kan omdøbes i
brugerfladen. Begge sensorer placeres under en enhed med barnets navn.

### Dagssensor

Sensorens state er antallet af relevante plan- og beskedpunkter. Attributterne
indeholder:

- `fra_dato` og `til_dato`;
- `dage` for dags dato og næste dag;
- klasseplanens tekst og lektioner;
- SFO-planens tekst, når en SFO-plan findes;
- `vigtigt` med korte, klassificerede beskedresuméer;
- `kilder` med adresser til de anvendte ugeplaner.

### Ugesensor

Sensorens state er ISO-ugen, eksempelvis `2026-W35`. Attributterne indeholder:

- `ugeplan_tekst` med den komplette klasse- og SFO-ugeplan som almindelig tekst;
- `klasse_ugeplan_tekst` og `sfo_ugeplan_tekst` som separate tekstfelter;
- ugens første og sidste dato;
- generelle tekster fra klasse- og SFO-planen;
- alle hverdage med tekst og lektioner;
- relevante beskedresuméer fra de seneste syv dage;
- kildeadresser.

Home Assistant begrænser en sensors state til 255 tegn. Derfor ligger det
strukturerede indhold i attributterne, mens state holdes kort og egnet til
automations.

Tekstattributterne filtrerer ikke ugeplanens indhold. De indeholder både
**Generelt**, alle ugedage inklusive allerede passerede dage, lektier,
påmindelser, aktiviteter og skemaoplysninger. `ugeplan_tekst` kan derfor bruges
direkte som kontekst til en lokal AI-model uden først at samle de strukturerede
felter manuelt.

## Opdatering

Fintra henter data ved opsætning og ved opstart af Home Assistant. Derefter
opdateres data én gang i døgnet. En manuel opdatering kan startes med handlingen
`homeassistant.update_entity` på en af Fintra-sensorerne. Coordinatoren deler
samme hentning mellem alle sensorer, så en manuel opdatering opdaterer hele
kontoens datasæt.

## Eksempel på automation

Dette eksempel sender en notifikation, når dagssensoren indeholder punkter:

```yaml
automation:
  - alias: "Fintra morgenstatus"
    triggers:
      - trigger: time
        at: "06:30:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.vester_dag
        above: 0
    actions:
      - action: notify.notify
        data:
          title: "Skoleplan"
          message: >-
            {{ state_attr('sensor.vester_dag', 'dage') }}
```

## Datasikkerhed

Ugeplaner og skolebeskeder kan indeholde personoplysninger. Overvej derfor:

- hvem der har adgang til Home Assistant;
- om sensorattributter skal medtages i Recorder-historikken;
- om backups er krypterede;
- aldrig at dele diagnostik eller logs med adgangskoder eller rå cookies.

Fintra sender ikke data til en AI-tjeneste. En eventuel lokal AI-opsummering bør
laves separat i Home Assistant, eksempelvis med en lokal Ollama-installation.

## Begrænsninger

- ForældreIntra har ikke et officielt offentligt API. Ændringer i HTML eller
  interne JSON-endpoints kan derfor kræve en opdatering af Fintra.
- Første version understøtter kun almindeligt login, ikke UNI-Login.
- Beskedklassificeringen er regelbaseret og kan både overse formuleringer og
  markere et punkt, der ikke er vigtigt.
- Kun den aktuelle uges klasse- og SFO-planer hentes.
- Integrationens brugerflade opdager børn ved første opsætning. Hvis skolen
  tilføjer et nyt barn, skal integrationen slettes og tilføjes igen i denne
  første version.

## Udvikling og test

Opret et virtuelt miljø og installér testafhængighederne:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest
```

Parser-tests bruger sanitiserede HTML- og JSON-fixtures og indeholder ingen
rigtige loginoplysninger eller elevdata.
