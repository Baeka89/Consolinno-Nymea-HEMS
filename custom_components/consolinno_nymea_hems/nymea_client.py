"""Nymea Client for Consolinno Nymea HEMS integration."""
import asyncio
import json
import ssl
import logging
from typing import Optional, Dict, Any, Callable

_LOGGER = logging.getLogger(__name__)


def ha_language_to_nymea_locale(ha_language: str) -> str:
    """Wandelt Home Assistants Sprachcode (z.B. 'de', 'en-GB') in das von
    Nymea/Qt erwartete Locale-Format ('de_DE', 'en_US') um.

    Nymea übersetzt beim JSONRPC.Hello-Handshake alle Anzeige-Namen (States,
    Actions, Settings, Thing-Klassen) automatisch in die per "locale"
    angeforderte Sprache - das ist die eigentliche Lösung für mehrsprachige
    Entity-Namen, nicht HAs eigenes translation_key-System (das für unsere
    dynamisch von Nymea kommenden Namen nicht greifen kann).
    Unbekannte Sprachen fallen auf Englisch zurück - Nymea selbst würde bei
    einer ihm unbekannten Locale ohnehin auf seine eigene Standardsprache
    zurückfallen.
    """
    if not ha_language:
        return "en_US"
    lang = ha_language.replace("-", "_")
    parts = lang.split("_")
    if len(parts) == 2 and len(parts[1]) == 2:
        return f"{parts[0].lower()}_{parts[1].upper()}"
    common_defaults = {
        "de": "de_DE", "en": "en_US", "fr": "fr_FR", "es": "es_ES",
        "it": "it_IT", "nl": "nl_NL", "pl": "pl_PL", "pt": "pt_PT",
        "sv": "sv_SE", "da": "da_DK", "no": "nb_NO", "fi": "fi_FI",
    }
    return common_defaults.get(parts[0].lower(), "en_US")

class NymeaClient:
    def __init__(self, host: str, port: int, username: str, password: str, ssl_enabled: bool = True,
                 locale: str = "en_US"):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._ssl_enabled = ssl_enabled
        self._locale = locale
        self._token = None
        self._reader = None
        self._writer = None
        self._server_info = {}
        self._listener_task = None
        self._keepalive_task = None
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._on_event_callback: Optional[Callable] = None
        self._request_id = 10
        self._is_connected = False
        # Verhindert parallele Verbindungsversuche, wenn mehrere Coroutinen
        # (z.B. Coordinator-Refresh + ein manueller Service-Call) gleichzeitig
        # _ensure_connected() aufrufen.
        self._connect_lock = asyncio.Lock()

    async def _create_ssl_context(self) -> ssl.SSLContext:
        """Erstellt einen toleranten SSL-Kontext für TLSv1.3 und selbstsignierte Zertifikate."""
        # PROTOCOL_TLS_CLIENT ist notwendig für moderne TLS-Standards
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        
        # Da dein Gateway ein selbstsigniertes Zertifikat nutzt, 
        # müssen wir die Überprüfung komplett abschalten.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        # Setzt das Sicherheitslevel herab, um auch mit 'unsicheren' lokalen Zertifikaten zu arbeiten
        context.set_ciphers('DEFAULT@SECLEVEL=1')
        return context

    async def connect(self):
        """Öffentlicher Einstiegspunkt: stellt sicher, dass eine Verbindung besteht."""
        await self._ensure_connected()

    async def _ensure_connected(self):
        """Baut die Verbindung zum Nymea Gateway auf und räumt alte Ressourcen auf.

        Der eigentliche Verbindungsaufbau läuft hinter einem Lock, damit bei
        gleichzeitigen Aufrufen (z.B. Coordinator-Refresh und ein paralleler
        Service-Call) nicht zwei Sockets gleichzeitig geöffnet werden.
        """
        need_reauth = False

        async with self._connect_lock:
            # Falls die Verbindung als unterbrochen markiert ist, Cleanup vor dem Neuversuch
            if not self._is_connected or self._writer is None or self._writer.transport.is_closing():
                _LOGGER.debug("Verbindung unterbrochen oder Re-Initialisierung nötig. Cleanup...")
                await self.close_connection()

            if self._is_connected and self._writer:
                return

            _LOGGER.debug(f"Öffne Verbindung zu {self._host}:{self._port} (SSL: {self._ssl_enabled})...")

            # SSL-Kontext nur erstellen, wenn SSL in der Integration aktiviert ist
            ssl_context = await self._create_ssl_context() if self._ssl_enabled else None

            try:
                # Verbindung aufbauen mit 15s Timeout für den TLS-Handshake
                # WICHTIG: "limit" stark erhöht (Standard ist nur 64 KB!).
                # JSONRPC.Introspect liefert die komplette, selbstbeschreibende
                # API-Doku des Gateways zurück - das kann mehrere hundert KB
                # bis einige MB groß sein und hat mit dem Standard-Limit sofort
                # "Separator is found, but chunk is longer than limit" ausgelöst,
                # was den kompletten Listener (und damit die Verbindung) abstürzen
                # ließ. 10 MB sind für jede realistische Nymea-Antwort mehr als
                # genug Puffer, auch für sehr große GetThings-Antworten.
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port, ssl=ssl_context, limit=10_000_000),
                    timeout=15
                )
                self._is_connected = True

                # Tasks für Listener (Datenempfang) und Keepalive (Verbindung halten) starten
                self._listener_task = asyncio.create_task(self._listen())
                self._keepalive_task = asyncio.create_task(self._keepalive())

                _LOGGER.debug(f"Socket-Verbindung hergestellt zu {self._host}")

                # Merken, ob nach dem Lock noch ein Re-Login nötig ist (Re-Connect Case)
                need_reauth = bool(self._token)

            except Exception as e:
                self._is_connected = False
                _LOGGER.error(f"Socket-Verbindung fehlgeschlagen: {e}")
                # Ressourcen sofort wieder freigeben, um Sockets nicht zu blockieren
                await self.close_connection()
                raise

        # Re-Authentifizierung bewusst AUSSERHALB des Locks: authenticate() läuft
        # wieder über _send_request() -> _ensure_connected(), was sonst mit dem
        # (nicht wiedereintrittsfähigen) Lock einen Deadlock verursachen würde.
        if need_reauth:
            await self.authenticate()

    async def _keepalive(self):
        """Sendet alle 30 Sekunden einen Ping, um den Socket offen zu halten."""
        try:
            while self._is_connected:
                await asyncio.sleep(30)
                if self._is_connected:
                    try:
                        # Ein einfacher JSONRPC.Hello Call dient als Herzschlag
                        await self._send_request("JSONRPC.Hello")
                    except Exception:
                        _LOGGER.debug("Keepalive fehlgeschlagen, Verbindung verloren.")
                        self._is_connected = False
                        break
        except asyncio.CancelledError:
            pass

    async def _listen(self):
        """Listener-Schleife für eingehende JSONRPC-Nachrichten."""
        try:
            while self._is_connected and self._reader:
                line = await self._reader.readline()
                if not line:
                    _LOGGER.warning("Nymea-Verbindung vom Server geschlossen.")
                    break
                
                raw_data = line.decode().strip()
                if not raw_data:
                    continue
                
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    continue

                msg_id = data.get("id")

                # KRITISCHER BUGFIX: Nymea-Notifications haben EBENFALLS ein
                # "id"-Feld - das ist aber ein eigener, serverseitig hochgezählter
                # Zähler, völlig unabhängig von unseren Request-IDs! Erkennbar
                # sind Notifications am Feld "notification" (nicht "method").
                # Bisher wurde hier zuerst auf "method" geprüft (das Nymea für
                # Notifications gar nicht benutzt) und die id direkt gegen
                # pending_requests gematcht. Sobald sich die beiden Zahlenräume
                # überschnitten haben (was bei aktivem Betrieb mit vielen
                # State-Change-Notifications schnell passiert), wurde eine
                # Notification fälschlich als Antwort auf eine unserer eigenen
                # Anfragen behandelt - die wartende Anfrage bekam dann falsche
                # Daten, die echte Antwort ging verloren. Das erklärt, warum der
                # erste Aufruf nach dem Verbindungsaufbau immer klappte (noch
                # keine Notifications im Umlauf), aber jedes weitere Update
                # danach zunehmend unzuverlässig wurde.
                notification_name = data.get("notification") or data.get("method")

                if notification_name is not None:
                    # Eindeutig eine Notification -> NIEMALS gegen pending_requests
                    # matchen, egal welchen Wert ihre eigene "id" zufällig hat.
                    if self._on_event_callback:
                        # KRITISCHER BUGFIX: _on_event_callback (siehe
                        # handle_nymea_event in __init__.py) ist eine SYNCHRONE,
                        # mit HAs @callback dekorierte Funktion, die intern
                        # SELBST hass.async_create_task(...) aufruft, um echte
                        # async-Arbeit einzuplanen. Sie ist KEINE Coroutine-
                        # Funktion und ihr Rückgabewert ist None.
                        # asyncio.create_task(None) crashte deshalb bei JEDER
                        # einzelnen Notification sofort mit "a coroutine was
                        # expected, got None" - dieser Fehler wurde weiter unten
                        # von der äußeren except-Klausel aufgefangen, hat aber
                        # dabei den KOMPLETTEN Listener-Loop beendet (siehe
                        # finally: self._is_connected = False), was einen
                        # Reconnect erzwang. Da Notifications erst seit Kurzem
                        # aktiviert sind (siehe authenticate()), ist dieser Bug
                        # jetzt bei praktisch jeder Notification aufgetreten.
                        # Fix: direkt (synchron) aufrufen, nicht in create_task()
                        # verpacken. Zusätzlich mit eigenem try/except
                        # abgesichert, damit ein Fehler in der Callback-
                        # Verarbeitung nie wieder den ganzen Listener/die
                        # Verbindung mit reißen kann - nur diese eine
                        # Notification würde dann verloren gehen.
                        try:
                            self._on_event_callback(data)
                        except Exception as cb_err:
                            _LOGGER.error(f"Fehler beim Verarbeiten einer Notification: {cb_err}")
                    continue

                # Erst JETZT, nachdem Notifications ausgeschlossen sind, als
                # Antwort auf eine unserer eigenen Anfragen behandeln.
                if msg_id is not None and msg_id in self._pending_requests:
                    future = self._pending_requests.pop(msg_id)
                    if not future.done():
                        future.set_result(data)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error(f"Fehler im Listener-Loop: {e}")
        finally:
            self._is_connected = False

    async def _send_request(self, method: str, params: Dict = None) -> Dict:
        """Sendet eine Anfrage und wartet auf die Antwort (Response)."""
        await self._ensure_connected()
        self._request_id += 1
        current_id = self._request_id
        
        request = {
            "id": current_id,
            "method": method,
            "params": params or {},
        }
        if self._token:
            request["token"] = self._token
        
        future = asyncio.get_running_loop().create_future()
        self._pending_requests[current_id] = future
        
        try:
            payload = (json.dumps(request) + "\n").encode()
            self._writer.write(payload)
            await self._writer.drain()
            # 10 Sekunden Zeit für die Antwort vom Gateway
            response = await asyncio.wait_for(future, timeout=10)
        except Exception as e:
            if current_id in self._pending_requests:
                self._pending_requests.pop(current_id)
            self._is_connected = False 
            raise e

        # BUGFIX: Nymea antwortet bei nicht existierenden/fehlgeschlagenen
        # Methoden mit {"status": "error", "error": "..."} statt einer
        # Transport-Exception. Das wurde bisher als "gültige" Antwort
        # durchgereicht - z.B. hat ein "No such method"-Fehler bei
        # IsCloudConnected trotzdem eine (dann nicht-funktionale) Entity
        # entstehen lassen. Ab jetzt wird das zentral als Fehler erkannt,
        # damit sich jeder Aufrufer einfach auf try/except verlassen kann.
        # (Beachte: das betrifft nur Protokoll-Fehler wie "unbekannte Methode",
        # NICHT z.B. falsche Zugangsdaten bei JSONRPC.Authenticate - das läuft
        # weiterhin über "status": "success" + "params": {"success": false}.)
        if response.get("status") == "error":
            raise RuntimeError(f"Nymea-API-Fehler bei '{method}': {response.get('error')}")

        return response

    async def authenticate(self):
        """Führt den Login am Nymea Server durch."""
        # WICHTIG für mehrsprachige Entity-Namen: locale mitschicken, damit
        # Nymea alle Anzeige-Namen (States/Actions/Settings/Thing-Klassen)
        # direkt in der gewünschten Sprache zurückliefert - siehe
        # ha_language_to_nymea_locale() weiter oben.
        hello = await self._send_request("JSONRPC.Hello", {"locale": self._locale})
        p = hello.get("params", {})
        self._server_info = {
            "uuid": p.get("uuid"),
            "version": p.get("version"),
            "name": p.get("name")
        }

        auth_params = {
            "username": self._username,
            "password": self._password,
            "deviceName": "HomeAssistant"
        }
        auth = await self._send_request("JSONRPC.Authenticate", auth_params)
        res = auth.get("params", {})
        if not res.get("success"):
            raise ValueError("Ungültige Zugangsdaten (Credentials)")
        self._token = res.get("token")

        # BUGFIX: Laut offizieller Nymea-Doku sind Notifications auf JEDER
        # NEUEN Verbindung standardmäßig DEAKTIVIERT und müssen nach jedem
        # (Re-)Connect erneut aktiviert werden ("If you get disconnected, the
        # notifications have to be enabled again on the next connection").
        # Da authenticate() bei jedem Connect UND jedem Reconnect läuft, ist
        # das hier der richtige Ort. Ohne diesen Aufruf bekommen wir NIE
        # Push-Notifications - unser fertiger Notification-Handler
        # (siehe _listen()) lief bisher komplett leer, die Integration hat
        # sich rein auf Polling verlassen.
        await self._send_request("JSONRPC.SetNotificationStatus", {"enabled": True})

    def set_event_callback(self, callback: Callable):
        """Setzt die Funktion, die bei neuen Events aufgerufen wird."""
        self._on_event_callback = callback

    async def get_things(self):
        """Abruf aller Geräte (Things) vom Gateway."""
        res = await self._send_request("Integrations.GetThings")
        return res.get("params", {}).get("things", [])

    async def get_thing_class_details(self, thing_class_id):
        """Abruf der Details für eine bestimmte Geräteklasse."""
        res = await self._send_request("Integrations.GetThingClasses", {"thingClassIds": [thing_class_id]})
        return res.get("params", {}).get("thingClasses", [])

    async def set_thing_state(self, thing_id: str, state_type_id: str, value: Any):
        """Setzt einen Zustand (z.B. Schalter an/aus) an einem Gerät."""
        params = {
            "thingId": thing_id,
            "stateTypeId": state_type_id,
            "value": value
        }
        return await self._send_request("Integrations.SetThingState", params)

    async def execute_action(self, thing_id: str, action_type_id: str, action_params: Dict[str, Any] = None):
        """Führt eine Nymea-Aktion (ActionType) an einem Thing aus.

        Im Gegensatz zu set_thing_state() ist eine Aktion nicht an genau einen
        Zustand gebunden, sondern kann 0..n benannte Parameter haben (z.B.
        "Netz Exportgrenze festlegen" mit percent + inverterNominalPower).
        """
        params = {
            "thingId": thing_id,
            "actionTypeId": action_type_id,
            "params": [
                {"paramTypeId": param_id, "value": value}
                for param_id, value in (action_params or {}).items()
            ],
        }
        return await self._send_request("Integrations.ExecuteAction", params)

    async def set_thing_settings(self, thing_id: str, settings: Dict[str, Any] = None):
        """Ändert 1..n Settings (settingsTypes) eines Things auf einmal.

        Settings sind ein eigenes Nymea-Konzept, getrennt von States und
        Actions: persistente Konfigurationswerte (z.B. Batteriekapazität,
        PV-Ausrichtung), die zur Laufzeit änderbar sind, ohne das Thing neu
        einzurichten. API-Methode: Integrations.SetThingSettings.
        """
        params = {
            "thingId": thing_id,
            "settings": [
                {"paramTypeId": param_id, "value": value}
                for param_id, value in (settings or {}).items()
            ],
        }
        return await self._send_request("Integrations.SetThingSettings", params)

    # ------------------------------------------------------------------
    # "Hems"-API: eine ZWEITE, komplett von Integrations.* GETRENNTE
    # JSON-RPC-Namespace, die vom Consolinno-Plugin (nymea-energy-plugin-
    # consolinno) bereitgestellt wird. Darüber laufen u.a. PV-Einstellungen,
    # der Überlastschutz (HousholdPhaseLimit) und der dynamische Stromtarif -
    # alles Dinge, die NICHT über normale Things/States/Actions/Settings
    # abrufbar sind, da sie nicht am einzelnen Thing hängen, sondern am
    # HEMS-Optimizer selbst.
    # ------------------------------------------------------------------

    async def call_hems_method(self, method_name: str, params: Dict = None) -> Dict:
        """Generischer Aufruf einer beliebigen Hems.*-Methode.

        method_name z.B. "GetPvConfigurations", "SetPvConfiguration",
        "GetHousholdPhaseLimit", "SetHousholdPhaseLimit", ...
        Gibt das komplette "params"-Feld der Antwort zurück (roh), damit wir
        beim ersten Kontakt mit dieser API die tatsächliche Feldstruktur
        live sehen können, statt sie zu erraten.
        """
        res = await self._send_request(f"Hems.{method_name}", params or {})
        return res.get("params", {})

    async def get_pv_configurations(self) -> list:
        """Ruft alle PV-Konfigurationen über die Hems-API ab (Breitengrad,
        Längengrad, Dachneigung, Ausrichtung, Spitzenleistung o.ä. - siehe
        Diagnose-Log für die tatsächlichen Feldnamen)."""
        result = await self.call_hems_method("GetPvConfigurations")
        return result.get("pvConfigurations", [])

    async def get_household_phase_limit(self) -> Any:
        """Ruft das Haushalts-Phasenlimit (vermutlich der 'Überlastschutz' aus
        der App) über die Hems-API ab."""
        result = await self.call_hems_method("GetHousholdPhaseLimit")
        return result.get("housholdPhaseLimit")

    async def set_pv_configuration(self, pv_configuration: Dict[str, Any]):
        """Setzt eine komplette PV-Konfiguration (Breitengrad, Längengrad,
        Dachneigung, Ausrichtung, Spitzenleistung, ...).

        WICHTIG: Die Nymea-API (Hems.SetPvConfiguration) erwartet das
        VOLLSTÄNDIGE PvConfiguration-Objekt, keine Teilmenge geänderter Felder.
        Fehlende Felder würden vermutlich auf ihren Default zurückgesetzt -
        daher müssen beim Aufruf IMMER alle Felder (inkl. pvThingId) mitgeschickt
        werden, auch die gerade nicht geänderten.
        """
        return await self.call_hems_method("SetPvConfiguration", {"pvConfiguration": pv_configuration})

    async def set_household_phase_limit(self, value: int):
        """Setzt das Haushalts-Phasenlimit (Überlastschutz) über die Hems-API."""
        return await self.call_hems_method("SetHousholdPhaseLimit", {"housholdPhaseLimit": value})

    # ------------------------------------------------------------------
    # Fernverbindung - läuft NICHT über "Cloud" (das war eine falsche
    # Vermutung, JSONRPC.IsCloudConnected existiert nicht), sondern über
    # einen "TunnelProxyServer" in der Configuration-API - bestätigt durch
    # JSONRPC.Introspect. Eine TunnelProxyServerConfiguration enthält eine
    # echte Server-Adresse/Port/SSL-Konfiguration (kein einfaches Bool!) -
    # deshalb lesen wir die aktuell hinterlegte Konfiguration einmal aus und
    # verwenden GENAU DIESE beim Wieder-Einschalten erneut, statt Adress-
    # /Port-Werte zu erfinden.
    # ------------------------------------------------------------------

    async def get_configurations(self) -> Dict[str, Any]:
        """Ruft ALLE Server-Konfigurationen ab (TCP/WebSocket/TunnelProxy/...).
        Bestätigte Methode laut JSONRPC.Introspect."""
        res = await self._send_request("Configuration.GetConfigurations")
        return res.get("params", {})

    async def set_tunnel_proxy_server_configuration(self, config: Dict[str, Any]):
        """Setzt (aktiviert) eine TunnelProxyServerConfiguration.

        WICHTIG: config muss eine ECHTE, zuvor über get_configurations()
        ausgelesene Konfiguration sein (address/port/sslEnabled/...) - wir
        erfinden hier bewusst keine Verbindungsdaten.
        """
        return await self._send_request(
            "Configuration.SetTunnelProxyServerConfiguration",
            {"configuration": config},
        )

    async def delete_tunnel_proxy_server_configuration(self, config_id: str):
        """Deaktiviert die Fernverbindung (löscht die TunnelProxyServerConfiguration)."""
        return await self._send_request(
            "Configuration.DeleteTunnelProxyServerConfiguration", {"id": config_id}
        )

    async def introspect(self) -> Dict[str, Any]:
        """Ruft die komplette (selbstbeschreibende) API-Dokumentation vom
        Gateway ab. Dient hier NUR zur Diagnose: damit lässt sich die exakte
        Methode für Fernverbindung/Reboot/Shutdown zweifelsfrei bestätigen,
        statt sie zu erraten (siehe __init__.py)."""
        res = await self._send_request("JSONRPC.Introspect")
        return res.get("params", {})

    async def initiate_reboot(self):
        """Startet das GESAMTE System (Betriebssystem) neu.
        Methodenname bestätigt durch JSONRPC.Introspect-Diagnose."""
        return await self._send_request("System.Reboot")

    async def initiate_shutdown(self):
        """Fährt das GESAMTE System (Betriebssystem) herunter.
        Methodenname bestätigt durch JSONRPC.Introspect-Diagnose."""
        return await self._send_request("System.Shutdown")

    async def restart_nymea_service(self):
        """Startet nur den nymea-Dienst (nymead) neu, nicht das ganze System.
        Methodenname bestätigt durch JSONRPC.Introspect-Diagnose."""
        return await self._send_request("System.Restart")

    async def close_connection(self):
        """Stoppt alle Hintergrund-Tasks und schließt den Socket sauber."""
        self._is_connected = False
        
        # Laufende Tasks abbrechen
        for task in [self._listener_task, self._keepalive_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
        
        self._listener_task = None
        self._keepalive_task = None

        if self._writer:
            try:
                _LOGGER.debug("Schließe Socket Writer...")
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), timeout=5)
            except Exception as e:
                _LOGGER.debug(f"Fehler beim Schließen des Writers: {e}")
        
        self._writer = None
        self._reader = None
        
        # Alle noch wartenden Anfragen löschen
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()