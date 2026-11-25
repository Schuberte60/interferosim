# src/interferosim/io/visibility.py -- visibilities as FITS binary table (interferosim.io.visibility)
"""Visibilities (:class:`~interferosim.visdata.VisData`) as FITS binary table.

The file format is the one of ``aas6sim`` ``visibility.py`` (aas6sim
1.3.1): a primary HDU without data and a binary table ``EXTNAME =
VISIBILITY`` with one row per integration and the columns

=========  ===========  ========================================
column     unit         content
=========  ===========  ========================================
TIME       d            MJD (UTC) of the middle of the interval
HA         deg          hour angle
UU VV WW   wavelengths  baseline components at ``RESTFRQ``
VISREAL    Jy           real part of the visibility
VISIMAG    Jy           imaginary part of the visibility
WEIGHT     1/Jy2        weight 1/sigma^2
=========  ===========  ========================================

and the header keywords of :mod:`interferosim.io.headers` plus
``UVUNIT``, ``ANT1``, ``ANT2`` and ``BASELINE`` (m).

Extensions of Interferosim (a file with one channel and one baseline is
read by ``aas6sim.visibility.read_visibility`` unchanged; the extensions
use only additional keywords, columns and tables, which aas6sim ignores):

* **channels** -- with ``n_chan > 1`` the columns ``VISREAL``,
  ``VISIMAG`` and ``WEIGHT`` are vectors of length ``n_chan`` and a
  second table ``EXTNAME = FREQUENCY`` (column ``FREQ`` in Hz) holds the
  channel frequencies; ``RESTFRQ`` is always ``freq_hz[0]``, the frequency
  of ``UU``/``VV``/``WW``;
* **baselines** -- the keywords ``NBASELIN`` and ``BLNAM001`` ...
  hold the baseline names (``"A-B"``); with more than one baseline the
  column ``BASELIDX`` (integer) gives the baseline of each row. With one
  baseline ``ANT1``/``ANT2`` are the two parts of its name (aas6sim).

The descriptive keywords of ``VisData.header`` are written to the table
header and read back as dictionary (``HISTORY`` lines as list under
``"HISTORY"``); ``ORIGIN`` and ``DATE`` are always set by the writer.

>>> import tempfile, pathlib
>>> import numpy as np
>>> from interferosim.visdata import VisData
>>> vd = VisData(time_mjd=[60000.0, 60000.1], ha_deg=[0.0, 36.1], u=[10.0, 20.0],
...              v=[0.0, 5.0], w=[0.0, 0.0], baseline=[0, 0], vis=[1 + 1j, 2 - 1j],
...              weight=[4.0, 4.0], freq_hz=[1.42e9], header={"OBJECT": "test"})
>>> path = pathlib.Path(tempfile.mkdtemp()) / "vis.fits"
>>> back = read_visibility(write_visibility(path, vd))
>>> np.allclose(back.vis, vd.vis), float(back.freq_hz[0]), back.baseline_names, back.header["OBJECT"]
(True, 1420000000.0, ['A-B'], 'test')

Version 1.0.6 (2026-11-25): first version (requirement F-DAT-2).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

import numpy as np
from astropy.io import fits

from ..visdata import VisData
from .headers import OBS_KEYS, SIM_KEYWORD, add_observation, base_header, is_simulated

__all__ = ["EXTNAME", "FREQ_EXTNAME", "UV_UNIT", "COLUMNS", "write_visibility",
           "read_visibility"]

EXTNAME = "VISIBILITY"
FREQ_EXTNAME = "FREQUENCY"
UV_UNIT = "wavelengths"

#: Columns of the table: name, FITS format (one channel), unit, comment
#: (names, formats and units as in aas6sim 1.3.1).
COLUMNS = [
    ("TIME", "D", "d", "MJD (UTC) of the middle of the interval"),
    ("HA", "D", "deg", "hour angle"),
    ("UU", "D", UV_UNIT, "baseline east-west"),
    ("VV", "D", UV_UNIT, "baseline north-south"),
    ("WW", "D", UV_UNIT, "baseline towards the source"),
    ("VISREAL", "D", "Jy", "real part of the visibility"),
    ("VISIMAG", "D", "Jy", "imaginary part of the visibility"),
    ("WEIGHT", "D", "1/Jy2", "weight = 1/sigma^2"),
]
_CHANNEL_COLUMNS = {"VISREAL", "VISIMAG", "WEIGHT"}
BASELINE_COLUMN = "BASELIDX"

# keywords of base_header() that may come from VisData.header
_BASE_ARGS = {"TELESCOP": "telescope", "INSTRUME": "instrument", "OBSERVER": "observer",
              "OBJECT": "object_name", "DATE-OBS": "date_obs"}
# keywords that describe the table itself; not part of VisData.header
_STRUCTURE = re.compile(r"^(XTENSION|BITPIX|NAXIS\d*|PCOUNT|GCOUNT|TFIELDS|EXTNAME|EXTVER"
                        r"|T(TYPE|FORM|UNIT|DIM|NULL|SCAL|ZERO|DISP)\d+|COMMENT|HISTORY|"
                        r"UVUNIT|ANT1|ANT2|NBASELIN|BLNAM\d{3}|NCHAN)$")
_MAX_BASELINES = 999


def _header_value(value: Any) -> Any:
    """A value FITS can store (bool, int, float, str); others as text."""
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    return str(value)


def _key(name: str) -> str:
    """FITS keyword for a dictionary key (HIERARCH for long or unusual names)."""
    key = str(name).upper()
    if len(key) <= 8 and re.fullmatch(r"[A-Z0-9_-]+", key):
        return key
    return "HIERARCH " + key


def write_visibility(
    path: Union[str, Path],
    data: VisData,
    *,
    baseline_m: Optional[float] = None,
    meta: Optional[Dict[str, Any]] = None,
    overwrite: bool = True,
    **hdr_kw: Any,
) -> Path:
    """Write :class:`VisData` as FITS file (format of aas6sim, see module).

    Parameters
    ----------
    path
        Output file (``.fits``).
    data
        The visibilities; ``data.header`` supplies descriptive keywords.
    baseline_m
        Length of the baseline in metres (keyword ``BASELINE``, as in
        aas6sim); only with one baseline.
    meta
        Observation parameters with the names of aas6sim
        (``bandwidth_hz``, ``tsys_k``, ``exposure_s``, ``obsra_deg``,
        ``obsdec_deg``, ``sitelat_deg``, ``sitelon_deg``, ``siteelev_m``);
        other names become keywords ``name[:8].upper()`` as in aas6sim.
        ``freq_hz`` is not allowed here: ``RESTFRQ`` is ``data.freq_hz[0]``.
    overwrite
        Replace an existing file.
    **hdr_kw
        Arguments of :func:`~interferosim.io.headers.base_header`
        (``telescope``, ``instrument``, ``observer``, ``object_name``,
        ``date_obs``, ``simulated``, ``history``, ``extra``); they take
        priority over ``data.header``.

    Returns
    -------
    Path
        The written file.
    """
    path = Path(path)
    meta = dict(meta or {})
    if "freq_hz" in meta:
        raise ValueError("meta['freq_hz'] is not allowed: RESTFRQ is data.freq_hz[0]")
    names = list(data.baseline_names)
    if not 1 <= len(names) <= _MAX_BASELINES:
        raise ValueError(f"1 to {_MAX_BASELINES} baseline names required, got {len(names)}")
    if data.n_rows and (data.baseline.min() < 0 or data.baseline.max() >= len(names)):
        raise ValueError("baseline index outside baseline_names")
    if baseline_m is not None and len(names) > 1:
        raise ValueError("baseline_m is only defined for one baseline")

    # ---- header: base keywords, then the further keywords of data.header
    given = {k.upper(): v for k, v in data.header.items()}
    kw = dict(hdr_kw)
    for key, arg in _BASE_ARGS.items():
        if arg not in kw and given.get(key) not in (None, ""):
            kw[arg] = str(given[key])
    kw.setdefault("simulated", is_simulated(given) if SIM_KEYWORD in given else True)
    history = list(kw.pop("history", None) or [])
    old_history = given.get("HISTORY") or []
    if isinstance(old_history, str):
        old_history = [old_history]
    hdr = base_header(history=[str(h) for h in old_history] + history, **kw)
    for key, value in given.items():
        if key in ("ORIGIN", "DATE", "HISTORY", SIM_KEYWORD) or key in _BASE_ARGS:
            continue
        if value is None or _STRUCTURE.match(key):
            continue
        hdr[_key(key)] = _header_value(value)

    hdr["EXTNAME"] = EXTNAME
    hdr["UVUNIT"] = (UV_UNIT, "unit of UU/VV/WW")
    if len(names) == 1:
        ant1, _, ant2 = names[0].partition("-")
        hdr["ANT1"] = (ant1[:68], "station 1")
        hdr["ANT2"] = (ant2[:68], "station 2")
    if baseline_m is not None:
        hdr["BASELINE"] = (float(baseline_m), "m, length of the baseline")
    add_observation(hdr, freq_hz=float(data.freq_hz[0]),
                    **{k: v for k, v in meta.items() if k in OBS_KEYS})
    for key, value in meta.items():
        if key not in OBS_KEYS:
            hdr[key[:8].upper()] = _header_value(value)
    hdr["NBASELIN"] = (len(names), "number of baselines (interferosim)")
    for k, name in enumerate(names, start=1):
        hdr[f"BLNAM{k:03d}"] = (str(name)[:68], f"name of baseline index {k - 1}")
    hdr["NCHAN"] = (data.n_chan, "number of channels (interferosim)")

    # ---- columns
    n_chan = data.n_chan
    one = n_chan == 1
    arrays = {"TIME": data.time_mjd, "HA": data.ha_deg, "UU": data.u, "VV": data.v,
              "WW": data.w,
              "VISREAL": data.vis.real[:, 0] if one else data.vis.real,
              "VISIMAG": data.vis.imag[:, 0] if one else data.vis.imag,
              "WEIGHT": data.weight[:, 0] if one else data.weight}
    cols = []
    for name, fmt, unit, comment in COLUMNS:
        if name in _CHANNEL_COLUMNS and not one:
            fmt = f"{n_chan}D"
        cols.append(fits.Column(name=name, format=fmt, unit=unit, array=arrays[name]))
        hdr.add_comment(f"{name} [{unit}] - {comment}")
    if len(names) > 1:
        cols.append(fits.Column(name=BASELINE_COLUMN, format="J", array=data.baseline))
        hdr.add_comment(f"{BASELINE_COLUMN} - index of the baseline (BLNAMnnn = index + 1)")
    if not one:
        hdr.add_comment(f"VISREAL, VISIMAG, WEIGHT: vectors of {n_chan} channels, "
                        f"frequencies in table {FREQ_EXTNAME}")

    hdus = [fits.PrimaryHDU(), fits.BinTableHDU.from_columns(cols, header=hdr, name=EXTNAME)]
    if not one:
        fhdr = fits.Header()
        fhdr["NCHAN"] = (n_chan, "number of channels")
        fhdr.add_comment("FREQ [Hz] - frequency of the channel")
        hdus.append(fits.BinTableHDU.from_columns(
            [fits.Column(name="FREQ", format="D", unit="Hz", array=data.freq_hz)],
            header=fhdr, name=FREQ_EXTNAME))
    fits.HDUList(hdus).writeto(path, overwrite=overwrite)
    return path


def read_visibility(path: Union[str, Path], extname: str = EXTNAME,
                    freq_hz: Optional[Any] = None) -> VisData:
    """Read a visibility file of Interferosim or aas6sim as :class:`VisData`.

    Parameters
    ----------
    path
        FITS file with a table ``extname``.
    extname
        Name of the visibility table (default ``VISIBILITY``).
    freq_hz
        Channel frequencies; only needed for a file without ``RESTFRQ`` and
        without ``FREQUENCY`` table (given values take priority).

    Raises
    ------
    ValueError
        If the channel frequencies are unknown or do not match the table.
    """
    with fits.open(path) as hdul:
        hdu = hdul[extname]
        d = hdu.data
        hdr = hdu.header
        vis = (np.array(d["VISREAL"], dtype=float) + 1j * np.array(d["VISIMAG"], dtype=float))
        weight = np.array(d["WEIGHT"], dtype=float)
        if freq_hz is None:
            if FREQ_EXTNAME in hdul:
                freq_hz = np.array(hdul[FREQ_EXTNAME].data["FREQ"], dtype=float)
            elif "RESTFRQ" in hdr:
                freq_hz = [float(hdr["RESTFRQ"])]
            else:
                raise ValueError(f"{path}: no RESTFRQ and no {FREQ_EXTNAME} table; "
                                 "pass freq_hz")
        freq_hz = np.atleast_1d(np.asarray(freq_hz, dtype=float))
        if vis.ndim == 1:
            vis, weight = vis[:, None], weight[:, None]
        if vis.shape[1] != freq_hz.size:
            raise ValueError(f"{path}: {vis.shape[1]} channel(s) in the table, "
                             f"{freq_hz.size} frequency(ies)")

        if "NBASELIN" in hdr:
            names = [str(hdr[f"BLNAM{k:03d}"]) for k in range(1, int(hdr["NBASELIN"]) + 1)]
        elif "ANT1" in hdr or "ANT2" in hdr:
            names = [f"{hdr.get('ANT1', '')}-{hdr.get('ANT2', '')}"]
        else:
            names = ["A-B"]
        n = vis.shape[0]
        if BASELINE_COLUMN in d.columns.names:
            baseline = np.array(d[BASELINE_COLUMN], dtype=int)
        else:
            baseline = np.zeros(n, dtype=int)

        header: Dict[str, Any] = {}
        for card in hdr.cards:
            if not _STRUCTURE.match(card.keyword):
                header[card.keyword] = card.value
        history = [str(h) for h in hdr.get("HISTORY", [])]
        if history:
            header["HISTORY"] = history

        return VisData(time_mjd=np.array(d["TIME"], dtype=float),
                       ha_deg=np.array(d["HA"], dtype=float),
                       u=np.array(d["UU"], dtype=float), v=np.array(d["VV"], dtype=float),
                       w=np.array(d["WW"], dtype=float), baseline=baseline, vis=vis,
                       weight=weight, freq_hz=freq_hz, baseline_names=names, header=header)
