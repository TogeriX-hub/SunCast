"""
suncast.py - SunCast main program
Astronomical light/twilight times as a MeshCore bot, fully offline via astral.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional, Callable, Awaitable
from zoneinfo import ZoneInfo

import math

import yaml
from astral import LocationInfo
from astral.sun import sun, dusk, dawn
from astral.moon import moonrise, moonset, phase as moon_phase

try:
    import ephem
    EPHEM_AVAILABLE = True
except ImportError:
    EPHEM_AVAILABLE = False
    logger.warning("ephem library not installed – moon illumination will be approximate")

logger = logging.getLogger(__name__)

try:
    from meshcore import MeshCore
    MESHCORE_AVAILABLE = True
except ImportError:
    MESHCORE_AVAILABLE = False
    logger.warning("meshcore library not installed – simulator mode only")

# ── City coordinate table ──────────────────────────────────────────────────
# astral's built-in DB is too sparse for German cities

CITY_COORDS = {
    "stuttgart":      (48.7758,  9.1829,  "Stuttgart"),
    "münchen":        (48.1351, 11.5820,  "München"),
    "munchen":        (48.1351, 11.5820,  "München"),
    "munich":         (48.1351, 11.5820,  "München"),
    "berlin":         (52.5200, 13.4050,  "Berlin"),
    "hamburg":        (53.5753,  9.9950,  "Hamburg"),
    "frankfurt":      (50.1109,  8.6821,  "Frankfurt"),
    "köln":           (50.9333,  6.9500,  "Köln"),
    "koln":           (50.9333,  6.9500,  "Köln"),
    "cologne":        (50.9333,  6.9500,  "Köln"),
    "düsseldorf":     (51.2217,  6.7762,  "Düsseldorf"),
    "dusseldorf":     (51.2217,  6.7762,  "Düsseldorf"),
    "dortmund":       (51.5139,  7.4653,  "Dortmund"),
    "essen":          (51.4556,  7.0116,  "Essen"),
    "leipzig":        (51.3397, 12.3731,  "Leipzig"),
    "bremen":         (53.0793,  8.8017,  "Bremen"),
    "dresden":        (51.0504, 13.7373,  "Dresden"),
    "hannover":       (52.3759,  9.7320,  "Hannover"),
    "nürnberg":       (49.4521, 11.0767,  "Nürnberg"),
    "nurnberg":       (49.4521, 11.0767,  "Nürnberg"),
    "nuremberg":      (49.4521, 11.0767,  "Nürnberg"),
    "karlsruhe":      (49.0069,  8.4037,  "Karlsruhe"),
    "mannheim":       (49.4875,  8.4660,  "Mannheim"),
    "augsburg":       (48.3717, 10.8983,  "Augsburg"),
    "freiburg":       (47.9990,  7.8421,  "Freiburg"),
    "heidelberg":     (49.3988,  8.6724,  "Heidelberg"),
    "ulm":            (48.4011,  9.9876,  "Ulm"),
    "regensburg":     (49.0134, 12.1016,  "Regensburg"),
    "würzburg":       (49.7944,  9.9294,  "Würzburg"),
    "wurzburg":       (49.7944,  9.9294,  "Würzburg"),
    "sindelfingen":   (48.7139,  9.0033,  "Sindelfingen"),
    "böblingen":      (48.6833,  9.0167,  "Böblingen"),
    "boblingen":      (48.6833,  9.0167,  "Böblingen"),
    "tübingen":       (48.5216,  9.0576,  "Tübingen"),
    "tubingen":       (48.5216,  9.0576,  "Tübingen"),
    "heilbronn":      (49.1427,  9.2109,  "Heilbronn"),
    "reutlingen":     (48.4914,  9.2044,  "Reutlingen"),
    "pforzheim":      (48.8921,  8.6939,  "Pforzheim"),
    "konstanz":       (47.6779,  9.1732,  "Konstanz"),
    "ravensburg":     (47.7817,  9.6133,  "Ravensburg"),
    "wien":           (48.2082, 16.3738,  "Wien"),
    "vienna":         (48.2082, 16.3738,  "Wien"),
    "graz":           (47.0707, 15.4395,  "Graz"),
    "salzburg":       (47.8095, 13.0550,  "Salzburg"),
    "innsbruck":      (47.2692, 11.4041,  "Innsbruck"),
    "zürich":         (47.3769,  8.5417,  "Zürich"),
    "zurich":         (47.3769,  8.5417,  "Zürich"),
    "bern":           (46.9480,  7.4474,  "Bern"),
    "basel":          (47.5596,  7.5886,  "Basel"),
    "genf":           (46.2044,  6.1432,  "Genf"),
    "geneva":         (46.2044,  6.1432,  "Genf"),
    "london":         (51.5074, -0.1278,  "London"),
    "paris":          (48.8566,  2.3522,  "Paris"),
    "amsterdam":      (52.3676,  4.9041,  "Amsterdam"),
    "rom":            (41.9028, 12.4964,  "Rom"),
    "rome":           (41.9028, 12.4964,  "Rom"),
    "madrid":         (40.4168, -3.7038,  "Madrid"),
    "barcelona":      (41.3851,  2.1734,  "Barcelona"),
    "stockholm":      (59.3293, 18.0686,  "Stockholm"),
    "oslo":           (59.9139, 10.7522,  "Oslo"),
    "kopenhagen":     (55.6761, 12.5683,  "Kopenhagen"),
    "copenhagen":     (55.6761, 12.5683,  "Kopenhagen"),
    "helsinki":       (60.1699, 24.9384,  "Helsinki"),
    "tromsø":         (69.6496, 18.9560,  "Tromsø"),
    "tromso":         (69.6496, 18.9560,  "Tromsø"),
}


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(cfg: dict, path: str = "config.yaml"):
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def get_moon_phase_name(phase_days: float) -> tuple[str, int]:
    # Phase name from astral's 0-27.99 day value
    if phase_days < 1.75 or phase_days >= 26.25:
        name = "Neumond"
    elif phase_days < 7.0:
        name = "Zunehmend"
    elif phase_days < 8.75:
        name = "Halbmond (↑)"
    elif phase_days < 14.0:
        name = "Zunehmend"
    elif phase_days < 15.75:
        name = "Vollmond"
    elif phase_days < 21.0:
        name = "Abnehmend"
    elif phase_days < 22.75:
        name = "Halbmond (↓)"
    else:
        name = "Abnehmend"
    # Fallback illumination via cosine (used only if ephem unavailable)
    pct = int((1 - math.cos(math.pi * phase_days / 14.5)) / 2 * 100)
    pct = max(0, min(100, pct))
    return name, pct


def get_moon_illumination(target_date: date, at_time=None) -> int:
    """
    Returns accurate moon illumination % using ephem.
    at_time: aware datetime for current illumination; if None uses noon UTC of target_date.
    Falls back to cosine approximation if ephem not available.
    """
    if not EPHEM_AVAILABLE:
        phase_days = moon_phase(target_date)
        return int((1 - math.cos(math.pi * phase_days / 14.5)) / 2 * 100)

    moon = ephem.Moon()
    if at_time is not None:
        utc_time = at_time.astimezone(timezone.utc)
        moon.compute(utc_time.strftime("%Y/%m/%d %H:%M:%S"))
    else:
        moon.compute(f"{target_date.year}/{target_date.month:02d}/{target_date.day:02d} 12:00:00")
    return round(float(moon.phase))


def resolve_location(city_name: str, cfg_location: dict) -> Optional[LocationInfo]:
    tz = cfg_location.get("timezone", "Europe/Berlin")
    if city_name:
        key = city_name.lower().strip()
        if key in CITY_COORDS:
            lat, lon, display_name = CITY_COORDS[key]
            return LocationInfo(name=display_name, region="", timezone=tz,
                                latitude=lat, longitude=lon)
        return None
    # No city – use config
    name = cfg_location.get("default", "")
    if name:
        key = name.lower().strip()
        if key in CITY_COORDS:
            lat, lon, display_name = CITY_COORDS[key]
            return LocationInfo(name=display_name, region="", timezone=tz,
                                latitude=lat, longitude=lon)
    lat = cfg_location.get("lat", 0.0)
    lon = cfg_location.get("lon", 0.0)
    if lat and lon:
        return LocationInfo(name=name or "Standort", region="", timezone=tz,
                            latitude=lat, longitude=lon)
    return None


def parse_date(date_str: Optional[str]) -> Optional[date]:
    if not date_str:
        return None
    today = date.today()
    for fmt in ("%d.%m.%Y", "%d.%m"):
        try:
            d = datetime.strptime(date_str, fmt)
            if fmt == "%d.%m":
                d = d.replace(year=today.year)
                if d.date() < today - timedelta(days=1):
                    d = d.replace(year=today.year + 1)
            return d.date()
        except ValueError:
            continue
    return None


# ── MeshClient ─────────────────────────────────────────────────────────────

WsBroadcastFn = Callable[[dict], Awaitable[None]]


class MeshClient:
    """
    Handles MeshCore TCP connection for SunCast.
    Listens for bot commands on the configured channel and sends replies.
    Analog to WarnBridge's MeshSender, but bidirectional (receive + send).
    """

    def __init__(self, config: dict):
        mc = config.get("meshcore", {})
        self.host        = mc.get("host", "192.168.4.2")
        self.port        = int(mc.get("port", 4403))
        self.simulator   = mc.get("simulator", True)
        self.channel_idx = int(mc.get("channel_idx", 0))
        self.scope       = mc.get("scope", "*")
        self._mc         = None
        self._connected  = False
        self._ws_broadcast: Optional[WsBroadcastFn] = None

    def set_ws_broadcast(self, fn: WsBroadcastFn):
        self._ws_broadcast = fn

    async def connect(self) -> bool:
        if self.simulator:
            self._connected = True
            logger.info("MeshClient: Simulator-Modus aktiv")
            return True

        if not MESHCORE_AVAILABLE:
            logger.error("meshcore library nicht installiert – kein Mesh möglich")
            return False

        try:
            self._mc = await MeshCore.create_tcp(self.host, self.port)
            self._connected = True
            logger.info("MeshCore verbunden: %s:%d (Channel %s)",
                        self.host, self.port)
            await self._set_scope()
            return True
        except Exception as e:
            self._connected = False
            logger.error("MeshCore Verbindung fehlgeschlagen: %s", e)
            return False

    async def disconnect(self):
        self._connected = False
        if self._mc is not None:
            try:
                await self._mc.close()
            except Exception:
                pass
            self._mc = None
        logger.info("MeshCore getrennt")

    async def _set_scope(self):
        if self._mc is None:
            return
        try:
            await self._mc.commands.set_flood_scope(self.scope)
            logger.info("MeshCore Flood-Scope gesetzt: %s", self.scope)
        except Exception as e:
            logger.warning("set_flood_scope fehlgeschlagen: %s", e)

    async def send_reply(self, text: str) -> bool:
        """Send a reply to the configured channel."""
        if self.simulator:
            logger.info("[SIM OUT] %s", text)
            await self._notify_ws("out", "simulator", text)
            return True

        if not self._connected or self._mc is None:
            logger.warning("MeshCore nicht verbunden – versuche Reconnect")
            await self.connect()
            if not self._connected:
                return False

        try:
            await self._mc.commands.send_chan_msg(self.channel_idx, text)
            logger.info("[MESH OUT] %s", text)
            await self._notify_ws("out", "mesh", text)
            return True
        except Exception as e:
            logger.error("MeshCore send Fehler: %s", e)
            self._connected = False
            return False

    async def listen_loop(self, on_command):
        """
        Receive loop: waits for channel messages and calls
        on_command(sender, text) for every message starting with '/'.

        In simulator mode this loop just sleeps – commands come via
        the dashboard's /api/simulate endpoint instead.
        """
        if self.simulator:
            logger.info("MeshClient: receive loop inaktiv im Simulator-Modus")
            await asyncio.Event().wait()   # sleep forever, simulator drives input
            return

        if not self._connected or self._mc is None:
            await self.connect()
            if not self._connected:
                return

        logger.info("MeshClient: Lausche auf %s (channel_idx=%d)",
                    self.channel, self.channel_idx)

        while True:
            try:
                # meshcore library: wait for next incoming message
                msg = await self._mc.wait_for_msg()

                sender  = getattr(msg, "sender", "unknown")
                channel = getattr(msg, "channel_idx", -1)
                text    = getattr(msg, "text", "") or ""

                # Only process messages on our channel
                if channel != self.channel_idx:
                    continue

                logger.debug("MeshCore IN [ch%d] %s: %s", channel, sender, text)
                await self._notify_ws("in", sender, text)

                if text.strip().startswith("/"):
                    await on_command(sender, text.strip())

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("MeshCore receive Fehler: %s", e)
                self._connected = False
                # Reconnect after brief pause
                await asyncio.sleep(10)
                await self.connect()

    async def _notify_ws(self, direction: str, sender: str, text: str):
        if self._ws_broadcast:
            await self._ws_broadcast({
                "type": "mesh_msg",
                "direction": direction,
                "sender": sender,
                "text": text,
                "time": datetime.now().strftime("%H:%M:%S"),
            })

    async def update_config(self, host: str, port: int, channel_idx: int,
                            scope: str, simulator: bool):
        """Live config update from dashboard. Reconnects if needed."""
        was_real = not self.simulator
        self.host        = host
        self.port        = port
        self.channel_idx = channel_idx
        self.scope       = scope
        self.simulator   = simulator

        if was_real and not simulator:
            # Was real, still real – reconnect to apply new settings
            await self.disconnect()
            await self.connect()
        elif not was_real and simulator:
            # Switching to simulator
            await self.disconnect()
            self._connected = True
        elif was_real is False and not simulator:
            # Was simulator, switching to real
            await self.connect()

    def status(self) -> dict:
        return {
            "simulator":   self.simulator,
            "connected":   self._connected,
            "host":        self.host if not self.simulator else None,
            "port":        self.port if not self.simulator else None,
            "channel_idx": self.channel_idx,
            "scope":       self.scope,
        }


# ── Bot logic ──────────────────────────────────────────────────────────────

class SunCastBot:
    def __init__(self, config: dict):
        self.cfg = config
        self.loc_cfg = config.get("location", {})
        self.bot_cfg = config.get("bot", {})
        self.twilight_label = self.bot_cfg.get("twilight_label", "Tageslicht bis")
        self.tz = ZoneInfo(self.loc_cfg.get("timezone", "Europe/Berlin"))

    def handle(self, text: str) -> list[str]:
        text = text.strip()
        if not text.startswith("/"):
            return []
        parts = text.split()
        cmd = parts[0].lower()
        try:
            if cmd == "/sonne":
                return self._cmd_sonne(parts[1:])
            elif cmd == "/mond":
                return self._cmd_mond(parts[1:])
            elif cmd == "/tag":
                return self._cmd_tag(parts[1:])
            elif cmd == "/hilfe":
                return self._cmd_hilfe()
            else:
                return [f"Unbekannter Befehl: {cmd} – /hilfe für Übersicht"]
        except Exception as e:
            logger.error("Bot error for '%s': %s", text, e, exc_info=True)
            return ["Fehler bei der Berechnung. Bitte erneut versuchen."]

    def _get_default_location(self) -> Optional[LocationInfo]:
        return resolve_location("", self.loc_cfg)

    def _cmd_sonne(self, args: list[str]) -> list[str]:
        city = None
        date_arg = None
        for arg in args:
            parsed = parse_date(arg)
            if parsed:
                date_arg = parsed
            else:
                city = arg

        if city:
            loc = resolve_location(city, self.loc_cfg)
            if not loc:
                return [f"Ort '{city}' nicht bekannt. Tipp: /sonne Stuttgart"]
        else:
            loc = self._get_default_location()
            if not loc:
                return ["Kein Standort gesetzt. Tipp: /sonne Stuttgart"]

        target_date = date_arg or date.today()
        tz = ZoneInfo(loc.timezone)
        s = sun(loc.observer, date=target_date, tzinfo=tz)
        twilight_end = dusk(loc.observer, date=target_date, tzinfo=tz, depression=6)

        aufgang    = s["sunrise"].strftime("%H:%M")
        untergang  = s["sunset"].strftime("%H:%M")
        tageslicht = twilight_end.strftime("%H:%M")
        datum_str  = target_date.strftime("%d.%m.")

        line1 = f"{loc.name} {datum_str}  ↑{aufgang}  ↓{untergang}"
        line2 = f"{self.twilight_label}: {tageslicht}"
        combined = f"{line1}  {line2}"
        if len(combined) <= 120:
            return [combined]
        return [line1, line2]

    def _cmd_mond(self, args: list[str]) -> list[str]:
        date_arg = None
        for arg in args:
            parsed = parse_date(arg)
            if parsed:
                date_arg = parsed

        loc = self._get_default_location()
        target_date = date_arg or date.today()
        phase_val  = moon_phase(target_date)
        phase_name, _ = get_moon_phase_name(phase_val)
        # Use current time for today, noon for future/past dates
        if date_arg is None:
            phase_pct = get_moon_illumination(target_date, at_time=datetime.now(timezone.utc))
        else:
            phase_pct = get_moon_illumination(target_date)
        datum_str = target_date.strftime("%d.%m.")

        if loc:
            tz = ZoneInfo(loc.timezone)
            try:
                rise = moonrise(loc.observer, date=target_date, tzinfo=tz)
                sett = moonset(loc.observer, date=target_date, tzinfo=tz)
                rise_str = rise.strftime("%H:%M") if rise else "–"
                set_str  = sett.strftime("%H:%M") if sett else "–"
                line = f"Mond {datum_str}: {phase_name} ({phase_pct}%)  ↑{rise_str}  ↓{set_str}"
            except Exception:
                line = f"Mond {datum_str}: {phase_name} ({phase_pct}%)"
        else:
            line = f"Mond {datum_str}: {phase_name} ({phase_pct}%)"
        return [line]

    def _cmd_tag(self, args: list[str]) -> list[str]:
        city = args[0] if args else None
        if city:
            loc = resolve_location(city, self.loc_cfg)
            if not loc:
                return [f"Ort '{city}' nicht bekannt. Tipp: /tag Stuttgart"]
        else:
            loc = self._get_default_location()
            if not loc:
                return ["Kein Standort gesetzt. Tipp: /tag Stuttgart"]

        tz = ZoneInfo(loc.timezone)
        today = date.today()
        s = sun(loc.observer, date=today, tzinfo=tz)
        day_len   = s["sunset"] - s["sunrise"]
        total_min = int(day_len.total_seconds() / 60)
        h, m = divmod(total_min, 60)

        year = today.year
        longest_date,  longest_min  = _longest_day(loc, year, tz)
        shortest_date, shortest_min = _shortest_day(loc, year, tz)
        lh, lm = divmod(longest_min, 60)
        sh, sm = divmod(shortest_min, 60)

        line1 = f"{loc.name} heute: {h}h {m}min Tageslicht"
        line2 = (f"Max {longest_date.strftime('%d.%m.')}: {lh}h {lm:02d}min  "
                 f"Min {shortest_date.strftime('%d.%m.')}: {sh}h {sm:02d}min")
        combined = f"{line1}  |  {line2}"
        if len(combined) <= 120:
            return [combined]
        return [line1, line2]

    def _cmd_hilfe(self) -> list[str]:
        return ["Befehle: /sonne [Ort] [Datum]  /mond [Datum]  /tag [Ort]  /hilfe"]

    def today_summary(self, city: Optional[str] = None) -> dict:
        if city:
            loc = resolve_location(city, self.loc_cfg)
        else:
            loc = self._get_default_location()

        if not loc:
            return {"error": "Kein Standort konfiguriert"}

        today = date.today()
        tz = ZoneInfo(loc.timezone)
        try:
            s              = sun(loc.observer, date=today, tzinfo=tz)
            twilight_end   = dusk(loc.observer, date=today, tzinfo=tz, depression=6)
            twilight_start = dawn(loc.observer, date=today, tzinfo=tz, depression=6)
            tomorrow       = today + timedelta(days=1)
            s_tom          = sun(loc.observer, date=tomorrow, tzinfo=tz)
            twilight_end_tom = dusk(loc.observer, date=tomorrow, tzinfo=tz, depression=6)

            phase_val  = moon_phase(today)
            phase_name, _ = get_moon_phase_name(phase_val)
            phase_pct = get_moon_illumination(today, at_time=datetime.now(timezone.utc))
            try:
                rise = moonrise(loc.observer, date=today, tzinfo=tz)
                sett = moonset(loc.observer, date=today, tzinfo=tz)
            except Exception:
                rise, sett = None, None

            day_len   = s["sunset"] - s["sunrise"]
            total_min = int(day_len.total_seconds() / 60)
            now_local = datetime.now(tz)

            return {
                "location":          loc.name,
                "timezone":          loc.timezone,
                "date":              today.isoformat(),
                "now":               now_local.strftime("%H:%M"),
                "sunrise":           s["sunrise"].strftime("%H:%M"),
                "sunset":            s["sunset"].strftime("%H:%M"),
                "dawn":              twilight_start.strftime("%H:%M"),
                "dusk":              twilight_end.strftime("%H:%M"),
                "twilight_label":    self.twilight_label,
                "day_minutes":       total_min,
                "tomorrow_sunrise":  s_tom["sunrise"].strftime("%H:%M"),
                "tomorrow_sunset":   s_tom["sunset"].strftime("%H:%M"),
                "tomorrow_dusk":     twilight_end_tom.strftime("%H:%M"),
                "moon_phase_name":   phase_name,
                "moon_phase_pct":    phase_pct,
                "moon_rise":         rise.strftime("%H:%M") if rise else "–",
                "moon_set":          sett.strftime("%H:%M") if sett else "–",
            }
        except Exception as e:
            logger.error("today_summary error: %s", e, exc_info=True)
            return {"error": str(e)}


def _time_to_angle(dt: datetime) -> float:
    minutes = dt.hour * 60 + dt.minute
    return (minutes / 1440.0) * 360.0


def _longest_day(loc: LocationInfo, year: int, tz: ZoneInfo) -> tuple[date, int]:
    best_date, best_min = date(year, 6, 21), 0
    for day_offset in range(150, 185):
        d = date(year, 1, 1) + timedelta(days=day_offset)
        try:
            s = sun(loc.observer, date=d, tzinfo=tz)
            mins = int((s["sunset"] - s["sunrise"]).total_seconds() / 60)
            if mins > best_min:
                best_min, best_date = mins, d
        except Exception:
            continue
    return best_date, best_min


def _shortest_day(loc: LocationInfo, year: int, tz: ZoneInfo) -> tuple[date, int]:
    best_date, best_min = date(year, 12, 21), 99999
    for day_offset in range(335, 366):
        d = date(year, 1, 1) + timedelta(days=day_offset)
        if d.year != year:
            break
        try:
            s = sun(loc.observer, date=d, tzinfo=tz)
            mins = int((s["sunset"] - s["sunrise"]).total_seconds() / 60)
            if mins < best_min:
                best_min, best_date = mins, d
        except Exception:
            continue
    return best_date, best_min


# ── Main application ───────────────────────────────────────────────────────

class SunCast:
    def __init__(self, config: dict):
        self.cfg        = config
        self.start_time = datetime.now(timezone.utc)
        self.bot        = SunCastBot(config)
        self.mesh       = MeshClient(config)
        self.web_ui     = None
        self._tasks: list[asyncio.Task] = []
        self._last_command:  Optional[str] = None
        self._last_response: Optional[str] = None

    @property
    def simulator(self) -> bool:
        return self.mesh.simulator

    async def handle_message(self, sender: str, text: str) -> Optional[list[str]]:
        """Process a bot command. Called from MeshCore listener or dashboard simulator."""
        text = text.strip()
        if not text.startswith("/"):
            return None

        logger.info("Command from %s: %s", sender, text)
        self._last_command  = text
        responses           = self.bot.handle(text)
        self._last_response = " | ".join(responses)

        # Push to dashboard
        if self.web_ui and hasattr(self.web_ui, "ws_broadcast"):
            await self.web_ui.ws_broadcast({
                "type":      "command",
                "sender":    sender,
                "command":   text,
                "responses": responses,
            })

        return responses

    async def _on_mesh_command(self, sender: str, text: str):
        """Callback from MeshClient.listen_loop – process and reply."""
        responses = await self.handle_message(sender, text)
        if responses:
            for reply in responses:
                await self.mesh.send_reply(reply)
                if len(responses) > 1:
                    await asyncio.sleep(0.5)   # brief gap between multi-part replies

    def status(self) -> dict:
        uptime_s = int((datetime.now(timezone.utc) - self.start_time).total_seconds())
        h, rem = divmod(uptime_s, 3600)
        m, s   = divmod(rem, 60)
        uptime_str = f"{h}h {m}m" if h else (f"{m}m {s}s" if m else f"{s}s")
        return {
            "uptime":        uptime_str,
            "mesh":          self.mesh.status(),
            "last_command":  self._last_command,
            "last_response": self._last_response,
            # top-level shortcuts used by dashboard
            "simulator":     self.simulator,
            "mesh_connected": self.mesh._connected,
        }

    async def start(self):
        logger.info("SunCast startet... (Simulator: %s)", self.simulator)

        # Connect MeshCore (or enter simulator mode)
        await self.mesh.connect()

        if self.web_ui:
            # Give web_ui a reference to mesh for live config changes
            self.web_ui.mesh = self.mesh
            self._tasks.append(asyncio.create_task(self.web_ui.run(), name="web_ui"))

        # Receive loop (sleeps in simulator mode)
        self._tasks.append(
            asyncio.create_task(
                self.mesh.listen_loop(self._on_mesh_command), name="mesh_listen"
            )
        )

        # Reconnect watcher (only relevant in real mode)
        self._tasks.append(
            asyncio.create_task(self._reconnect_loop(), name="reconnect")
        )

        logger.info("SunCast läuft. Dashboard: http://localhost:%d",
                    self.cfg.get("dashboard", {}).get("port", 8081))
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("SunCast wird beendet...")

    async def stop(self):
        logger.info("SunCast stoppt...")
        for task in self._tasks:
            task.cancel()
        await self.mesh.disconnect()

    async def _reconnect_loop(self):
        """Every 30s try to reconnect if real mode and disconnected."""
        while True:
            await asyncio.sleep(30)
            if not self.simulator and not self.mesh._connected:
                logger.info("MeshCore getrennt – versuche Reconnect...")
                try:
                    await self.mesh.connect()
                except Exception as e:
                    logger.error("Reconnect Fehler: %s", e)


async def main():
    setup_logging("INFO")

    config_path = "config.yaml"
    if not Path(config_path).exists():
        logger.error("config.yaml nicht gefunden!")
        sys.exit(1)

    config = load_config(config_path)
    app    = SunCast(config)

    try:
        from web_ui import WebUI
        app.web_ui = WebUI(app, config)
        logger.info("WebUI geladen (Port %d)",
                    config.get("dashboard", {}).get("port", 8081))
    except ImportError:
        logger.warning("web_ui.py nicht gefunden – ohne Dashboard")

    loop = asyncio.get_running_loop()

    def _shutdown():
        logger.info("Signal empfangen, beende...")
        asyncio.create_task(app.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    await app.start()


if __name__ == "__main__":
    asyncio.run(main())
