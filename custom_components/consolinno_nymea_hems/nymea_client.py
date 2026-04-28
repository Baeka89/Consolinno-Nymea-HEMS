"""Nymea Client for Consolinno Nymea HEMS integration."""
import asyncio
import json
import ssl
import logging
from typing import Optional, Dict, Any, Callable

_LOGGER = logging.getLogger(__name__)

class NymeaClient:
    def __init__(self, host: str, port: int, username: str, password: str, ssl_enabled: bool = True):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._ssl_enabled = ssl_enabled
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
        """Baut die Verbindung zum Nymea Gateway auf und räumt alte Ressourcen auf."""
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
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port, ssl=ssl_context),
                timeout=15
            )
            self._is_connected = True
            
            # Tasks für Listener (Datenempfang) und Keepalive (Verbindung halten) starten
            self._listener_task = asyncio.create_task(self._listen())
            self._keepalive_task = asyncio.create_task(self._keepalive())

            _LOGGER.info(f"Socket-Verbindung hergestellt zu {self._host}")
            
            # Authentifizierung durchführen, falls bereits ein Token existiert (Re-Connect Case)
            if self._token:
                await self.authenticate()

        except Exception as e:
            self._is_connected = False
            _LOGGER.error(f"Socket-Verbindung fehlgeschlagen: {e}")
            # Ressourcen sofort wieder freigeben, um Sockets nicht zu blockieren
            await self.close_connection()
            raise

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
                method = data.get("method")

                # Prüfen, ob es eine Antwort auf eine gestellte Anfrage ist
                if msg_id is not None and msg_id in self._pending_requests:
                    future = self._pending_requests.pop(msg_id)
                    if not future.done():
                        future.set_result(data)
                
                # Prüfen, ob es ein spontanes Event vom Gateway ist
                elif method:
                    if self._on_event_callback:
                        asyncio.create_task(self._on_event_callback(data))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error(f"Fehler im Listener-Loop: {e}")
        finally:
            self._is_connected = False

    async def _send_request(self, method: str, params: Dict = None) -> Dict:
        """Sendet eine Anfrage und wartet auf die Antwort (Response)."""
        await self.connect()
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
            return await asyncio.wait_for(future, timeout=10)
        except Exception as e:
            if current_id in self._pending_requests:
                self._pending_requests.pop(current_id)
            self._is_connected = False 
            raise e

    async def authenticate(self):
        """Führt den Login am Nymea Server durch."""
        hello = await self._send_request("JSONRPC.Hello")
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