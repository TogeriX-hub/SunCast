"""
web_ui.py - SunCast dashboard server
aiohttp on port 8081. Serves dashboard.html and a WebSocket for live updates.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web, WSMsgType

if TYPE_CHECKING:
    from suncast import SunCast

logger = logging.getLogger(__name__)


class WebUI:
    def __init__(self, app: "SunCast", config: dict):
        self.app  = app
        self.cfg  = config
        self.port = config.get("dashboard", {}).get("port", 8081)
        self.mesh = None   # set by SunCast.start() after MeshClient is ready
        self._ws_clients: set[web.WebSocketResponse] = set()
        self._aiohttp_app = web.Application()
        self._setup_routes()

    def _setup_routes(self):
        a = self._aiohttp_app
        a.router.add_get("/",                  self._handle_index)
        a.router.add_get("/dashboard.html",    self._handle_index)
        a.router.add_get("/ws",                self._handle_ws)
        a.router.add_get("/api/status",        self._handle_status)
        a.router.add_get("/api/today",         self._handle_today)
        a.router.add_post("/api/simulate",     self._handle_simulate)
        a.router.add_post("/api/config",       self._handle_config_location)
        a.router.add_post("/api/config/mesh",  self._handle_config_mesh)

    async def run(self):
        runner = web.AppRunner(self._aiohttp_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        logger.info("Dashboard läuft auf http://localhost:%d", self.port)
        await asyncio.Event().wait()

    # ── HTTP handlers ──────────────────────────────────────────────────────

    async def _handle_index(self, request: web.Request) -> web.Response:
        html_path = Path(__file__).parent / "dashboard.html"
        if not html_path.exists():
            return web.Response(text="dashboard.html nicht gefunden", status=404)
        return web.FileResponse(html_path)

    async def _handle_status(self, request: web.Request) -> web.Response:
        return web.json_response(self.app.status())

    async def _handle_today(self, request: web.Request) -> web.Response:
        city = request.query.get("city")
        return web.json_response(self.app.bot.today_summary(city))

    async def _handle_simulate(self, request: web.Request) -> web.Response:
        """POST /api/simulate  body: {"command": "/sonne Stuttgart"}"""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        command = body.get("command", "").strip()
        if not command:
            return web.json_response({"error": "No command"}, status=400)

        # Call bot directly – skip handle_message() to avoid double WS broadcast
        responses = self.app.bot.handle(command) or []
        self.app._last_command  = command
        self.app._last_response = " | ".join(responses)

        return web.json_response({
            "command":   command,
            "responses": responses,
            "timestamp": datetime.now().astimezone().strftime("%H:%M:%S"),
        })

    async def _handle_config_location(self, request: web.Request) -> web.Response:
        """POST /api/config  – update location and bot settings"""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        import yaml
        config_path = Path(__file__).parent / "config.yaml"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)

            loc = cfg.setdefault("location", {})
            if "default" in body:
                loc["default"] = body["default"]
            if "lat" in body:
                loc["lat"] = float(body["lat"])
            if "lon" in body:
                loc["lon"] = float(body["lon"])
            if "twilight_label" in body:
                cfg.setdefault("bot", {})["twilight_label"] = body["twilight_label"]

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

            # Reload live
            self.app.cfg = cfg
            from suncast import SunCastBot
            self.app.bot = SunCastBot(cfg)

            return web.json_response({"ok": True})
        except Exception as e:
            logger.error("Config save error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_config_mesh(self, request: web.Request) -> web.Response:
        """
        POST /api/config/mesh
        Body: { simulator, host, port, channel, channel_idx, scope }
        Saves to config.yaml and applies live.
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        import yaml
        config_path = Path(__file__).parent / "config.yaml"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)

            mc = cfg.setdefault("meshcore", {})
            if "simulator"   in body: mc["simulator"]   = bool(body["simulator"])
            if "host"        in body: mc["host"]        = str(body["host"])
            if "port"        in body: mc["port"]        = int(body["port"])
            if "channel_idx" in body: mc["channel_idx"] = int(body["channel_idx"])
            if "scope"       in body: mc["scope"]       = str(body["scope"])

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

            self.app.cfg = cfg

            # Apply live to MeshClient
            mesh = self.mesh or self.app.mesh
            if mesh:
                await mesh.update_config(
                    host        = mc.get("host", "192.168.4.2"),
                    port        = int(mc.get("port", 4403)),
                    channel_idx = int(mc.get("channel_idx", 0)),
                    scope       = mc.get("scope", "*"),
                    simulator   = bool(mc.get("simulator", True)),
                )

            # Notify dashboard of new status
            await self.ws_broadcast({"type": "status", "data": self.app.status()})

            return web.json_response({"ok": True})
        except Exception as e:
            logger.error("Mesh config save error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    # ── WebSocket ──────────────────────────────────────────────────────────

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws_clients.add(ws)
        logger.debug("WS client connected (%d total)", len(self._ws_clients))

        # Send initial state
        await ws.send_json({"type": "status", "data": self.app.status()})

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if data.get("type") == "command":
                            cmd = data.get("command", "")
                            responses = await self.app.handle_message("ws", cmd)
                            await ws.send_json({
                                "type":      "response",
                                "command":   cmd,
                                "responses": responses or [],
                            })
                    except Exception as e:
                        logger.warning("WS message error: %s", e)
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            self._ws_clients.discard(ws)
            logger.debug("WS client disconnected (%d total)", len(self._ws_clients))

        return ws

    async def ws_broadcast(self, data: dict):
        if not self._ws_clients:
            return
        dead = set()
        msg  = json.dumps(data)
        for ws in self._ws_clients:
            try:
                await ws.send_str(msg)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead
