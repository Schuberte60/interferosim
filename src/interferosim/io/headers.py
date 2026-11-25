# src/interferosim/io/headers.py -- common FITS header keywords (interferosim.io.headers)
"""Common FITS header keywords: origin, instrument, observation.

Port of ``aas6sim.headers`` (aas6sim 1.3.1) with English comments. The
keywords and their meaning are the same, so files written by Interferosim
and by ``aas6sim`` carry the same header. Only ``ORIGIN`` names the
writing package (``"interferosim <version>"`` instead of
``"aas6sim <version>"``).

The keyword ``SIMULATD`` is always set: a simulated file must remain
distinguishable from a measurement, even after several processing steps.

>>> hdr = base_header(object_name="Cyg A")
>>> hdr["ORIGIN"].split()[0], hdr["SIMULATD"], hdr["TELESCOP"], hdr["OBJECT"]
('interferosim', True, 'AAS6', 'Cyg A')
>>> add_observation(hdr, freq_hz=1.42e9, tsys_k=None)["RESTFRQ"]
1420000000.0
>>> "TSYS" in hdr, is_simulated(hdr)
(False, True)

Version 1.0.6 (2026-11-25): first version (requirement F-DAT-2).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Optional

from astropy.io import fits

__all__ = ["SIM_KEYWORD", "OBS_KEYS", "utc_now_iso", "base_header", "add_observation",
           "is_simulated"]

#: Keyword that marks simulated files (as in aas6sim).
SIM_KEYWORD = "SIMULATD"

#: Observation parameters: argument of :func:`add_observation` -> keyword and
#: comment (same keywords as aas6sim ``headers.add_observation``).
OBS_KEYS = {
    "freq_hz": ("RESTFRQ", "Hz, observing frequency"),
    "bandwidth_hz": ("BANDWID", "Hz, bandwidth"),
    "tsys_k": ("TSYS", "K, system temperature"),
    "exposure_s": ("EXPOSURE", "s, integration time per data point"),
    "obsra_deg": ("OBSRA", "deg, right ascension of the field centre"),
    "obsdec_deg": ("OBSDEC", "deg, declination of the field centre"),
    "sitelat_deg": ("SITELAT", "deg, geographic latitude"),
    "sitelon_deg": ("SITELONG", "deg, geographic longitude"),
    "siteelev_m": ("SITEELEV", "m, height above sea level"),
}


def utc_now_iso() -> str:
    """Current time (UTC) in the FITS format ``YYYY-MM-DDThh:mm:ss``."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def base_header(
    *,
    telescope: str = "AAS6",
    instrument: str = "",
    observer: str = "",
    object_name: str = "",
    date_obs: str = "",
    simulated: bool = True,
    history: Optional[list] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> fits.Header:
    """Header with the origin of the data (same arguments as aas6sim).

    ``extra`` adds further keywords (name -> value or (value, comment));
    ``history`` adds ``HISTORY`` lines. Empty strings are left out.
    """
    from .. import __version__
    hdr = fits.Header()
    hdr["ORIGIN"] = ("interferosim " + __version__, "writing package")
    hdr["DATE"] = (utc_now_iso(), "time the file was written (UTC)")
    hdr[SIM_KEYWORD] = (bool(simulated), "T = simulated data, not a measurement")
    if telescope:
        hdr["TELESCOP"] = (telescope, "telescope / installation")
    if instrument:
        hdr["INSTRUME"] = (instrument, "receiver / backend")
    if observer:
        hdr["OBSERVER"] = (observer, "observer")
    if object_name:
        hdr["OBJECT"] = (object_name, "observed object")
    if date_obs:
        hdr["DATE-OBS"] = (date_obs, "start of the observation (UTC)")
    for key, value in (extra or {}).items():
        hdr[key] = value
    for line in (history or []):
        hdr.add_history(line)
    return hdr


def add_observation(hdr: fits.Header, **values: Optional[float]) -> fits.Header:
    """Add observation parameters (keys of :data:`OBS_KEYS`); None is skipped.

    Unknown argument names raise a :class:`TypeError`, as in aas6sim.
    """
    unknown = set(values) - set(OBS_KEYS)
    if unknown:
        raise TypeError("unknown observation parameter(s): " + ", ".join(sorted(unknown)))
    for name, (key, comment) in OBS_KEYS.items():
        value = values.get(name)
        if value is not None:
            hdr[key] = (float(value), comment)
    return hdr


def is_simulated(hdr) -> bool:
    """True if the header (FITS header or dict) marks simulated data."""
    return bool(hdr.get(SIM_KEYWORD, False))
