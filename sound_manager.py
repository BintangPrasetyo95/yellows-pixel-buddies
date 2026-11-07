"""sound_manager.py - Lightweight, low-latency audio effect manager for Yellow's Pixel Buddies.

Features:
- Polyphonic WAV playback powered by PyQt5.QtMultimedia.QSoundEffect.
- Default is strictly MUTED / NO SOUND unless explicitly unmuted by user.
- Debouncing / cooldown tracking to prevent audio stutter during animation loops and rapid typing.
- Semantic alias resolution (e.g. 'bomb_explode', 'landing', 'text_blip') mapping to active sound files.
- Safe, non-blocking fallback handling if audio devices are unavailable.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtCore import QUrl
try:
    from PyQt5.QtMultimedia import QSoundEffect
    HAS_QT_MULTIMEDIA = True
except Exception:
    HAS_QT_MULTIMEDIA = False

log = logging.getLogger("yellows_pixel_buddies.audio")


def _resolve_sounds_dir() -> Path:
    """Locate the sounds directory in development mode or inside a frozen PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "sounds").exists():
            return exe_dir / "sounds"
        return Path(getattr(sys, "_MEIPASS", exe_dir)) / "sounds"
    script_dir = Path(__file__).resolve().parent
    return script_dir / "sounds"


# Semantic mapping from game event / role to active sound files in sounds/
SOUND_ALIASES: Dict[str, str] = {
    # --- Combat & Cat Bombs ---
    "bomb_explode": "snd_badexplosion.wav",
    "bomb": "snd_bomb.wav",
    "bomb_fall": "snd_bombfall.wav",
    "bomb_defuse": "snd_hit.wav",
    "hit": "snd_hit.wav",
    "laser": "snd_laz_c.wav",
    "player_hurt": "snd_hurt1.wav",
    "damage": "snd_damage.wav",
    "soul_break": "snd_break1.wav",
    "break1": "snd_break1.wav",
    "break2": "snd_break2.wav",
    "battle_enter": "snd_battleenter.wav",
    "battle_won": "snd_won.wav",

    # --- Dialogue Bubble & Typewriter ---
    "text_blip": "snd_text.wav",
    "bubble_pop": "snd_squeaky.wav",
    "bottle_pop": "snd_bottlepop.wav",
    "dialogue_next": "snd_select.wav",
    "voice_text": "snd_text.wav",
    "voice_alphys": "snd_txtal.wav",
    "voice_noelle": "snd_txtnoe.wav",
    "voice_susie": "snd_txtsus.wav",

    # --- Shop & Dark World Sanctuary UI ---
    "menu_move": "snd_menumove.wav",
    "menu_select": "snd_select.wav",
    "menu_error": "snd_cantselect.wav",
    "error": "snd_error.wav",
    "coin": "snd_coin.wav",
    "sell": "sell.wav",
    "goal_complete": "snd_levelup.wav",
    "save": "snd_save.wav",
    "character_switch": "character_switch.wav",
    "sanctuary_open": "character_switch.wav",

    # --- Physics & Movement ---
    "landing": "landing.wav",
    "jump": "snd_jump.wav",
    "wall_bounce": "snd_bump.wav",
    "grab": "snd_grab.wav",
    "gripped": "gripped.wav",
    "throw": "throw.wav",
    "throw2": "throw2.wav",
    "step1": "snd_step1.wav",
    "step2": "snd_step2.wav",

    # --- Emotions & Reactions ---
    "shocked": "shocked.wav",
    "laugh_short": "laugh_short.wav",
    "laugh_long": "laugh_long.wav",
    "embarrassed": "embarrased.wav",
    "embarrased": "embarrased.wav",
    "confused": "confused.wav",
    "wondering": "wondering.wav",
    "realize": "realize.wav",
    "burnt_cough": "snd_cough.wav",
    "cough": "snd_cough.wav",
    "applause": "snd_applause.wav",
    "awkward": "snd_awkward.wav",
    "sparkle": "snd_magicsprinkle.wav",

    # --- Alarms & Timers ---
    "alarm_bell": "snd_scissorbell.wav",
    "bell": "snd_bell.wav",
}

# Default cooldown in seconds to prevent sound spam/stutter
DEFAULT_COOLDOWNS: Dict[str, float] = {
    "text_blip": 0.065,
    "snd_text.wav": 0.065,
    "menu_move": 0.04,
    "snd_menumove.wav": 0.04,
    "landing": 0.18,
    "landing.wav": 0.18,
    "wall_bounce": 0.15,
    "snd_bump.wav": 0.15,
    "gripped": 0.4,
    "gripped.wav": 0.4,
    "grab": 0.3,
    "snd_grab.wav": 0.3,
    "shocked": 0.9,
    "laugh_short": 1.2,
    "laugh_long": 2.0,
    "embarrassed": 1.0,
    "wondering": 1.2,
    "confused": 0.9,
    "burnt_cough": 1.5,
    "cough": 1.5,
    "realize": 0.6,
    "bubble_pop": 0.3,
    "bottle_pop": 0.3,
    "coin": 0.1,
    "sell": 0.5,
    "step1": 0.20,
    "step2": 0.20,
    "battle_enter": 1.0,
    "save": 0.3,
    "awkward": 1.2,
    "break2": 1.5,
}

# Individual sound volume normalization multipliers
SOUND_VOLUME_NORMALIZATION: Dict[str, float] = {
    "text_blip": 0.45,
    "snd_text.wav": 0.45,
    "menu_move": 0.60,
    "snd_menumove.wav": 0.60,
    "menu_select": 0.75,
    "snd_select.wav": 0.75,
    "bomb_explode": 0.90,
    "snd_badexplosion.wav": 0.90,
    "laser": 0.70,
    "snd_laz_c.wav": 0.70,
    "landing": 0.85,
    "landing.wav": 0.85,
    "gripped": 0.80,
    "gripped.wav": 0.80,
    "bubble_pop": 0.70,
    "snd_squeaky.wav": 0.70,
    "step1": 0.30,
    "snd_step1.wav": 0.30,
    "step2": 0.30,
    "snd_step2.wav": 0.30,
    "battle_enter": 0.85,
    "snd_battleenter.wav": 0.85,
    "save": 0.80,
    "snd_save.wav": 0.80,
    "awkward": 0.75,
    "snd_awkward.wav": 0.75,
    "break2": 0.75,
    "snd_break2.wav": 0.75,
}


class SoundManager:
    """Manages audio effect loading, volume, cooldowns, and playback."""

    def __init__(self, sounds_dir: Optional[Path] = None, muted: bool = True, volume: float = 0.7) -> None:
        self._sounds_dir = Path(sounds_dir) if sounds_dir else _resolve_sounds_dir()
        # Default is strictly MUTED / NO SOUND until enabled by user
        self._muted: bool = bool(muted)
        self._volume: float = max(0.0, min(1.0, float(volume)))
        self._effects: Dict[str, QSoundEffect] = {}
        self._last_played_time: Dict[str, float] = {}

    @property
    def muted(self) -> bool:
        """True if sound is currently muted / disabled."""
        return self._muted

    @muted.setter
    def muted(self, val: bool) -> None:
        self.set_muted(val)

    def set_muted(self, muted: bool) -> None:
        """Update muted state. When muted, all play() calls return immediately."""
        self._muted = bool(muted)
        log.debug("SoundManager muted set to: %s", self._muted)

    @property
    def volume(self) -> float:
        """Master SFX volume (0.0 to 1.0)."""
        return self._volume

    @volume.setter
    def volume(self, val: float) -> None:
        self.set_volume(val)

    def set_volume(self, volume: float) -> None:
        """Set master SFX volume clamped between 0.0 and 1.0."""
        self._volume = max(0.0, min(1.0, float(volume)))
        # Update existing effect instances
        for name, eff in self._effects.items():
            norm = SOUND_VOLUME_NORMALIZATION.get(name, 1.0)
            eff.setVolume(self._volume * norm)

    def _resolve_sound_file(self, sound_name: str) -> Optional[Path]:
        """Resolve sound alias or filename to an existing file in sounds_dir."""
        filename = SOUND_ALIASES.get(sound_name, sound_name)
        if not filename.endswith(".wav") and not filename.endswith(".ogg"):
            filename += ".wav"
        target_path = self._sounds_dir / filename
        if target_path.exists():
            return target_path
        # Try direct name as fallback
        direct_path = self._sounds_dir / sound_name
        if direct_path.exists():
            return direct_path
        return None

    def play(self, sound_name: str, cooldown: Optional[float] = None, volume_scale: float = 1.0) -> bool:
        """Play sound effect with cooldown check and volume scaling.
        
        Returns True if the sound was played, False if muted/on cooldown/missing.
        """
        if self._muted:
            return False

        if not HAS_QT_MULTIMEDIA:
            return False

        now = time.perf_counter()
        required_cooldown = cooldown if cooldown is not None else DEFAULT_COOLDOWNS.get(sound_name, 0.05)
        last_played = self._last_played_time.get(sound_name, 0.0)
        if now - last_played < required_cooldown:
            return False

        sound_path = self._resolve_sound_file(sound_name)
        if sound_path is None:
            log.debug("Sound effect not found: %s", sound_name)
            return False

        try:
            key = str(sound_path)
            eff = self._effects.get(key)
            if eff is None:
                eff = QSoundEffect()
                eff.setSource(QUrl.fromLocalFile(str(sound_path.resolve())))
                self._effects[key] = eff

            norm = SOUND_VOLUME_NORMALIZATION.get(sound_name, 1.0)
            eff.setVolume(max(0.0, min(1.0, self._volume * norm * volume_scale)))
            eff.play()
            self._last_played_time[sound_name] = now
            return True
        except Exception as err:
            log.debug("Error playing sound '%s': %s", sound_name, err)
            return False

    def preload(self, sound_names: list[str]) -> None:
        """Preload common sound effects to ensure zero-latency initial playback."""
        if not HAS_QT_MULTIMEDIA:
            return
        for name in sound_names:
            sound_path = self._resolve_sound_file(name)
            if sound_path and str(sound_path) not in self._effects:
                try:
                    eff = QSoundEffect()
                    eff.setSource(QUrl.fromLocalFile(str(sound_path.resolve())))
                    norm = SOUND_VOLUME_NORMALIZATION.get(name, 1.0)
                    eff.setVolume(self._volume * norm)
                    self._effects[str(sound_path)] = eff
                except Exception as err:
                    log.debug("Could not preload sound '%s': %s", name, err)


# Global singleton instance
_sound_manager: Optional[SoundManager] = None


def get_sound_manager(sounds_dir: Optional[Path] = None) -> SoundManager:
    """Retrieve or initialize the global SoundManager singleton.
    
    Default state is strictly MUTED / NO SOUND.
    """
    global _sound_manager
    if _sound_manager is None:
        _sound_manager = SoundManager(sounds_dir=sounds_dir, muted=True, volume=0.7)
    return _sound_manager


def play_sound(sound_name: str, cooldown: Optional[float] = None, volume_scale: float = 1.0) -> bool:
    """Convenience helper to play sound through the global singleton."""
    return get_sound_manager().play(sound_name, cooldown=cooldown, volume_scale=volume_scale)
