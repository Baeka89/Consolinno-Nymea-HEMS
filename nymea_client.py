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
        loop = asyncio.get_running_loop()
        context = await loop.run_in_executor(None, ssl.create_default_context)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    async def connect(self):
        # Wenn der Writer existiert, aber die Transport-Schicht Probleme macht, schließen wir sicherheitshalber
        if self._writer and (self._writer.transport.is_closing() or not self._is_connected):
            await self.close_connection()

        if self._is_connected and self._writer:
            return

        _LOGGER.debug(f"Opening connection to {self._host}...")
        ssl_context = await self._create_ssl_context() if self._ssl_enabled else None
        
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port, ssl=ssl_context),
                timeout=10
            )
            self._is_connected = True
            
            # Alten Listener beenden, falls vorhanden
            if self._listener_task:
                self._listener_task.cancel()
            self._listener_task = asyncio.create_task(self._listen())

            # Heartbeat starten, um die Leitung offen zu halten
            if self._keepalive_task:
                self._keepalive_task.cancel()
            self._keepalive_task = asyncio.create_task(self._keepalive())

            _LOGGER.info(f"Socket connection established to {self._host}")
            
            # Falls wir bereits einen Token hatten, müssen wir uns meist neu authentifizieren
            if self._token:
                await self.authenticate()

        except Exception as e:
            self._is_connected = False
            _LOGGER.error(f"Socket connection failed: {e}")
            raise

    async def _keepalive(self):
        """Sendet alle 30 Sekunden einen Ping, damit der Socket nicht stirbt."""
        try:
            while self._is_connected:
                await asyncio.sleep(30)
                if self._is_connected:
                    try:
                        # Ein einfacher JSONRPC.Hello Call dient als Ping
                        await self._send_request("JSONRPC.Hello")
                    except Exception:
                        _LOGGER.debug("Keepalive failed, connection lost.")
                        self._is_connected = False
                        break
        except asyncio.CancelledError:
            pass

    async def _listen(self):
        try:
            while self._is_connected and self._reader:
                line = await self._reader.readline()
                if not line:
                    _LOGGER.warning("Nymea connection closed by server.")
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

                if msg_id is not None and msg_id in self._pending_requests:
                    future = self._pending_requests.pop(msg_id)
                    if not future.done():
                        future.set_result(data)
                
                elif method:
                    if self._on_event_callback:
                        asyncio.create_task(self._on_event_callback(data))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error(f"Error in listener loop: {e}")
        finally:
            self._is_connected = False
            # Hier kein automatischer close_connection Aufruf mehr, 
            # damit connect() beim nächsten Mal sauber aufräumt.

    async def _send_request(self, method: str, params: Dict = None) -> Dict:
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
            return await asyncio.wait_for(future, timeout=10)
        except Exception as e:
            if current_id in self._pending_requests:
                self._pending_requests.pop(current_id)
            self._is_connected = False # Bei Fehler Verbindung als tot markieren
            raise e

    async def authenticate(self):
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
            raise ValueError("Invalid credentials")
        self._token = res.get("token")

    def set_event_callback(self, callback: Callable):
        self._on_event_callback = callback

    async def get_things(self):
        res = await self._send_request("Integrations.GetThings")
        return res.get("params", {}).get("things", [])

    async def get_thing_class_details(self, thing_class_id):
        res = await self._send_request("Integrations.GetThingClasses", {"thingClassIds": [thing_class_id]})
        return res.get("params", {}).get("thingClasses", [])

    async def set_thing_state(self, thing_id: str, state_type_id: str, value: Any):
        params = {
            "thingId": thing_id,
            "stateTypeId": state_type_id,
            "value": value
        }
        return await self._send_request("Integrations.SetThingState", params)

    async def close_connection(self):
        self._is_connected = False
        if self._listener_task:
            self._listener_task.cancel()
            self._listener_task = None
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None