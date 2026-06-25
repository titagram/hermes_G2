# Hermes G2 Channel Design

Data: 2026-06-25

## Sintesi

HermesGlass deve evolvere da "chat sugli occhiali" a channel ufficiale per Hermes Agent su Even Realities G2.

L'app EvenHub deve restare un client leggero: mostra dati, raccoglie input da ring/tempie/microfono, gestisce profili di connessione e invia selezioni. La logica di azioni, scorciatoie, feed, alert, history, bootstrap e integrazioni deve vivere lato Hermes/bridge.

Principio guida: Hermes espone un catalogo semantico di azioni e dati; G2 decide layout, paginazione e interazione nel canvas 576x288.

## Obiettivi

- Rendere G2 un surface/gateway naturale per Hermes Agent, coerente con memoria, skill, tool, plugin e messaging gateway.
- Consentire uso senza voce tramite scorciatoie selezionabili dagli occhiali.
- Supportare dati ambientali e alert realtime senza hardcodare use case personali nell'app.
- Permettere bootstrap guidato del plugin Hermes G2 da mobile dopo configurazione `wss` + token.
- Supportare piu istanze Hermes tramite profili locali nell'app EvenHub.
- Restare proponibile come progetto open source sia a Hermes/Nous sia a Even Realities.

## Non Obiettivi Iniziali

- Non costruire una dashboard personale hardcoded dentro l'app G2.
- Non aggregare piu istanze Hermes in una dashboard unica nella prima versione.
- Non affidare l'installazione ufficiale a prompt liberi che eseguono comandi non strutturati.
- Non duplicare tutta la pipeline STT di Hermes nel design finale, anche se il bridge puo mantenere fallback locale.
- Non creare layout server-driven pixel-perfect: il server descrive semantica, non coordinate grafiche.

## Architettura

### Componenti

1. App EvenHub `HermesGlass`
   - Salva profili locali: nome, URL, token, ultimo uso, capability cache.
   - Connette al bridge via WebSocket.
   - Richiede surface semantica con `g2.surface.get`.
   - Renderizza home, lista, dettaglio, conferma, running state e alert.
   - Acquisisce audio PCM dagli occhiali e lo invia al backend quando l'utente usa la modalita voice.
   - Non contiene prompt personali o logica specifica di mail/server/calendar.

2. Bridge G2
   - Espone protocollo WebSocket compatibile con l'app.
   - Autentica token.
   - Traduce richieste G2 verso Hermes/plugin.
   - Gestisce streaming eventi: aggiornamenti surface, alert, stato azioni.
   - Mantiene fallback STT locale solo come compatibilita, non come fonte primaria ideale.

3. Plugin Hermes G2
   - Fonte ufficiale di actions, data feeds, alert, history e bootstrap status.
   - Espone tool/hook/endpoint interni per il bridge.
   - Usa configurazione Hermes per STT, memoria, skill, tool e integrazioni.
   - Definisce action catalog e dati periodici.

## Contratto Semantico G2

Il server espone azioni e dati, non layout.

Esempio:

```json
{
  "version": 1,
  "updatedAt": 1760000000000,
  "status": {
    "agent": "idle",
    "connection": "ok"
  },
  "items": [
    {
      "id": "server",
      "type": "data",
      "label": "SERVER",
      "summary": "56C RAM 41%",
      "detail": "CPU 12%\nRAM 41%\nDisk 68%\nTemp 56C",
      "priority": 10
    },
    {
      "id": "mail",
      "type": "action",
      "label": "MAIL",
      "summary": "12 unread",
      "action": {
        "kind": "run_prompt",
        "confirm": false,
        "risk": "read_only"
      }
    },
    {
      "id": "deploy",
      "type": "action",
      "label": "DEPLOY",
      "summary": "confirm required",
      "action": {
        "kind": "run_skill",
        "confirm": true,
        "risk": "dangerous"
      }
    }
  ]
}
```

Il prompt reale non deve necessariamente arrivare al G2. Il G2 manda solo l'id:

```json
{
  "method": "g2.action.run",
  "params": {
    "id": "mail"
  }
}
```

Hermes risolve `mail` nel prompt, skill o tool configurato lato server.

## Primitive UI Sugli Occhiali

Renderer fissi lato app:

- `home`: stato sintetico + lista di item.
- `list`: lista navigabile di azioni/dati.
- `detail`: testo paginato.
- `confirm`: conferma per azioni rischiose.
- `running`: stato azione in corso.
- `alert`: overlay temporaneo o item prioritario in cima.
- `voice`: modalita microfono.

Vincoli G2:

- Canvas 576x288.
- Massimo 12 container, massimo 8 text/list container.
- Un solo container con `isEventCapture: 1`.
- Testo e liste sono il canale primario; immagini solo per icone semplici o stati non frequenti.
- La paginazione resta lato app per controllare dimensioni e leggibilita.

## Navigazione

Target desiderato:

- Press: conferma/seleziona.
- Double press: indietro.
- Scroll up/down: cambia selezione o pagina.
- Long press: voice, solo se il SDK/hardware lo espone in modo affidabile.

Fallback se long press non e disponibile:

- `VOICE` e un item della home.
- Press su `VOICE` inizia ascolto.
- Press durante ascolto conclude e invia.

Uscita app:

- Va mantenuta una via sicura. Se double press diventa "indietro", l'uscita puo essere un item `EXIT` in settings oppure una gesture alternativa validata su hardware.

## Scorciatoie

Le scorciatoie sono Hermes Actions, non bottoni locali.

Campi minimi:

- `id`: identificatore stabile.
- `label`: testo corto per G2.
- `summary`: stato o descrizione breve.
- `risk`: `read_only`, `confirm`, `dangerous`.
- `confirm`: boolean.
- `presentation`: `summary`, `paged_text`, `data`, `alert`.

Configurazione:

- La sorgente di verita e Hermes/plugin.
- L'app mobile puo diventare un editor remoto delle action, ma non deve essere la fonte definitiva.
- Ogni modifica mobile invia comandi strutturati al server, ad esempio `g2.action.create` o `g2.action.update`.

## Dati, Feed E Alert

Il plugin Hermes G2 puo esporre feed periodici:

- Stato server: CPU, RAM, disco, temperatura, uptime.
- Mail: unread importanti, action required.
- Daily brief: pronto/non pronto.
- Alert: eventi realtime o priorita.
- History: ultime interazioni o risultati recenti.

Aggiornamenti:

- WebSocket push per realtime: `g2.surface.updated`, `g2.alert.push`.
- Polling fallback ogni 30-60 secondi: `g2.surface.refresh`.
- Cache locale nell'app per mostrare ultimo stato se il profilo e offline.

## Multi Istanza Hermes

Supportare piu istanze tramite profili locali.

Profilo:

```json
{
  "id": "home",
  "name": "Home Hermes",
  "url": "wss://home.example.com/ws",
  "tokenRef": "local-secret-home",
  "role": "personal",
  "default": true,
  "lastConnectedAt": 1760000000000,
  "capabilities": {
    "g2Surface": true,
    "bootstrap": true,
    "audioTranscribe": true
  }
}
```

Regola iniziale:

- Multi-profile local-first nell'app.
- Una sola istanza Hermes attiva sugli occhiali.
- Niente overview aggregata multi-Hermes nella prima versione.

UX:

- Telefono: add/edit/delete profile, test connection, set default, bootstrap plugin, reorder.
- Occhiali: voce `INSTANCE` o `PROFILE`, lista `HOME`, `WORK`, `LAB`, press per switch.
- Se il profilo e offline, mostra fallback e permette switch.

## Bootstrap Plugin

Obiettivo: dopo aver inserito URL e token, l'utente deve poter portare un server "bridge-only" a Hermes-native con flusso guidato.

Protocollo:

- `g2.bootstrap.status`: controlla plugin installato, versione, capacita.
- `g2.bootstrap.start`: avvia installazione strutturata.
- `g2.bootstrap.logs`: streaming step/log.

Esempio status:

```json
{
  "installed": false,
  "plugin": "hermes-g2",
  "expectedVersion": "0.1.0",
  "installAvailable": true,
  "method": "hermes_plugin_install"
}
```

Regole:

- Preferire installazione strutturata: repo nota, versione nota, manifest verificato, enable plugin, reload.
- Evitare prompt libero come percorso ufficiale.
- Consentire fallback dev: kickstart prompt guidato o comando manuale se il bridge non ha permessi.
- Mostrare step chiari sul telefono: cloning, installing, enabling, ready.

## Speech To Text

Hermes ha gia pipeline STT per voice mode e messaging platforms, con provider come local/faster-whisper, Groq e OpenAI.

Design finale:

- G2 adapter dovrebbe usare STT configurata da Hermes quando possibile.
- Il bridge puo mantenere fallback locale per compatibilita con API Hermes che non espongono `/v1/audio/transcriptions`.
- La surface deve indicare capability STT e provider effettivo.

Nota implementativa corrente:

- La versione server testata risponde 404 su `/v1/audio/transcriptions`.
- Il fallback locale `faster-whisper` e utile per far funzionare il sistema ora, ma non deve diventare il vincolo architetturale ufficiale.

## Trasporto E Sicurezza

Trasporti supportati:

- Tailscale: default personale/dev.
- Cloudflare Tunnel: opzione pro consigliata per utenti non tecnici.
- Custom reverse proxy/VPS: avanzato.

Sicurezza:

- Token obbligatorio per esposizioni non locali.
- Token salvati solo nello storage locale dell'app, mai nel surface JSON.
- Action con `risk=confirm` o `risk=dangerous` richiedono conferma esplicita.
- Bootstrap deve verificare sorgente e versione plugin.
- Evitare che il G2 possa inviare prompt di installazione arbitrari senza conferma.

## Roadmap Proposta

### Fase 1: Surface Semantica

- Aggiungere `g2.surface.get` e `g2.action.run` al bridge.
- Implementare renderer home/list/detail/confirm/running nell'app.
- Spostare shortcuts statiche lato bridge/server.
- Tenere voice come item `VOICE`.

### Fase 2: Profili Multipli

- Modello `profiles` nello storage EvenHub.
- UI mobile per add/edit/delete/test/default.
- Switch profilo dagli occhiali.
- Capability cache per profilo.

### Fase 3: Plugin Hermes G2

- Creare plugin installabile Hermes.
- Esportare action catalog e feed.
- Integrare history e alert.
- Preparare manifest e documentazione open source.

### Fase 4: Bootstrap Guidato

- `g2.bootstrap.status/start/logs`.
- Installazione plugin da repo/versione verificata.
- Fallback manuale quando non ci sono permessi.
- UI mobile con progress e remediation.

### Fase 5: Realtime E Alert

- Push `g2.surface.updated`.
- Push `g2.alert.push`.
- Feed periodici server status/mail/daily.
- Policy di priorita e non-disturbo.

### Fase 6: STT Hermes-Native

- Studiare e usare entrypoint STT Hermes ufficiale/plugin.
- Mantenere bridge fallback locale.
- Configurare timeout e provider in modo esplicito.

## Decisioni Gia Prese

- L'app G2 renderizza layout e paginazione.
- Il server espone solo azioni e dati.
- Scorciatoie gestite lato Hermes/plugin, sincronizzate al G2.
- Multi-profile locale nell'app, una istanza attiva alla volta.
- Bootstrap guidato strutturato, non prompt libero come percorso ufficiale.
- Dashboard personale come default experience, non come architettura hardcoded.

## Questioni Aperte

- Verificare se long press arriva davvero al plugin su hardware G2/R1.
- Decidere gesture finale per uscita se double press diventa indietro.
- Definire formato stabile per `presentation` e `risk`.
- Capire l'entrypoint piu pulito per usare STT Hermes dal plugin/bridge.
- Decidere repository, naming e licensing per proposta upstream.
- Definire se il bridge restera separato o diventera parte del plugin Hermes G2.

## Criteri Di Successo

- Un utente puo usare HermesGlass senza parlare, solo con scroll e press.
- Un utente puo cambiare istanza Hermes dal telefono o dagli occhiali.
- Un server puo esporre nuove action senza rebuild dell'app EvenHub.
- Alert e dashboard arrivano sugli occhiali senza polling aggressivo.
- Il progetto puo essere presentato come Hermes platform adapter e come EvenHub reference app avanzata.

