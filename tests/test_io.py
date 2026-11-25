# tests/test_io.py -- tests of interferosim.io (FITS visibilities, headers)
"""Tests of the FITS input/output ``interferosim.io`` (requirement F-DAT-2).

Checked:

* round trip VisData -> FITS -> VisData for one channel and one baseline
  (the aas6sim format), several channels (table ``FREQUENCY``) and several
  baselines (column ``BASELIDX``), including the header dictionary;
* compatibility with aas6sim: ``tests/data/aas6sim_1.3.1_visibility.fits``
  was written by ``aas6sim.visibility.write_visibility`` of aas6sim 1.3.1
  (6 rows, sigma = 0.5 Jy, Cyg A, 1420.40575 MHz, ANT1/ANT2 =
  WILHELMSBURG/MICHELBACH, BASELINE = 10 m). Interferosim reads it, and a
  file written by Interferosim has the same columns, formats, units and
  header keywords. If aas6sim is installed, it also reads the Interferosim
  file (otherwise that test is skipped);
* the marker ``SIMULATD`` and the error cases.

Version 1.0.6 (2026-11-25): first version.
"""

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from interferosim.io import base_header, is_simulated, read_visibility, write_visibility
from interferosim.io.headers import add_observation
from interferosim.visdata import VisData

AAS6 = Path(__file__).parent / "data" / "aas6sim_1.3.1_visibility.fits"


def make(n_rows=5, n_chan=1, names=("A-B",), seed=1, header=None):
    """A small VisData with random values."""
    rng = np.random.default_rng(seed)
    return VisData(time_mjd=60640.0 + np.arange(n_rows) / 1440, ha_deg=np.linspace(-5, 5, n_rows),
                   u=rng.normal(0, 100, n_rows), v=rng.normal(0, 100, n_rows),
                   w=rng.normal(0, 1, n_rows), baseline=np.arange(n_rows) % len(names),
                   vis=rng.normal(size=(n_rows, n_chan)) + 1j * rng.normal(size=(n_rows, n_chan)),
                   weight=rng.uniform(1, 4, (n_rows, n_chan)),
                   freq_hz=1.42e9 + 1e5 * np.arange(n_chan), baseline_names=list(names),
                   header=dict(header or {"OBJECT": "Cyg A", "SIMULATD": True}))


def same(a: VisData, b: VisData):
    for name in ("time_mjd", "ha_deg", "u", "v", "w", "vis", "weight", "freq_hz"):
        np.testing.assert_array_equal(getattr(a, name), getattr(b, name), err_msg=name)
    np.testing.assert_array_equal(a.baseline, b.baseline)
    assert a.baseline_names == b.baseline_names


# ---------------------------------------------------------------- round trips
def test_roundtrip_one_channel_one_baseline(tmp_path):
    vd = make(header={"OBJECT": "Cyg A", "SIMULATD": True, "TELESCOP": "TWO-HORNS",
                      "OBSRA": 299.868, "NOTE": "a text", "NINT": 3,
                      "long_key_name": 1.5})
    back = read_visibility(write_visibility(tmp_path / "v.fits", vd))
    same(vd, back)
    h = back.header
    assert h["OBJECT"] == "Cyg A" and h["TELESCOP"] == "TWO-HORNS" and h["SIMULATD"] is True
    assert h["OBSRA"] == 299.868 and h["NOTE"] == "a text" and h["NINT"] == 3
    assert h["LONG_KEY_NAME"] == 1.5
    assert h["RESTFRQ"] == 1.42e9 and h["ORIGIN"].startswith("interferosim ")
    with fits.open(tmp_path / "v.fits") as hdul:
        assert [hdu.name for hdu in hdul] == ["PRIMARY", "VISIBILITY"]
        assert hdul[1].header["ANT1"] == "A" and hdul[1].header["ANT2"] == "B"


def test_roundtrip_channels(tmp_path):
    vd = make(n_rows=7, n_chan=16)
    path = vd.to_fits(tmp_path / "v.fits")
    back = VisData.from_fits(path)
    same(vd, back)
    with fits.open(path) as hdul:
        assert hdul["VISIBILITY"].columns["VISREAL"].format == "16D"
        np.testing.assert_array_equal(hdul["FREQUENCY"].data["FREQ"], vd.freq_hz)
        assert hdul["VISIBILITY"].header["RESTFRQ"] == vd.freq_hz[0]


def test_roundtrip_baselines(tmp_path):
    vd = make(n_rows=9, n_chan=2, names=("A-B", "A-C", "B-C"))
    back = read_visibility(write_visibility(tmp_path / "v.fits", vd))
    same(vd, back)
    assert np.array_equal(back.select_baseline("A-C").vis, vd.select_baseline("A-C").vis)
    with fits.open(tmp_path / "v.fits") as hdul:
        assert "ANT1" not in hdul[1].header and hdul[1].header["NBASELIN"] == 3


def test_history_is_kept_and_extended(tmp_path):
    vd = make(header={"HISTORY": ["step 1"]})
    once = read_visibility(write_visibility(tmp_path / "a.fits", vd, history=["step 2"]))
    assert once.header["HISTORY"] == ["step 1", "step 2"]
    twice = read_visibility(write_visibility(tmp_path / "b.fits", once))
    assert twice.header["HISTORY"] == ["step 1", "step 2"]


# ---------------------------------------------------------------- aas6sim
def test_reads_aas6sim_file():
    vd = read_visibility(AAS6)
    assert vd.n_rows == 6 and vd.n_chan == 1
    assert vd.freq_hz[0] == 1.42040575e9
    assert vd.baseline_names == ["WILHELMSBURG-MICHELBACH"]
    np.testing.assert_allclose(vd.weight, 4.0)                    # sigma = 0.5 Jy
    np.testing.assert_allclose(vd.vis[[0, -1], 0], [1 - 0.5j, 2 + 0.5j])
    assert vd.header["ORIGIN"] == "aas6sim 1.3.1" and is_simulated(vd.header)
    assert vd.header["OBJECT"] == "Cyg A" and vd.header["BASELINE"] == 10.0
    assert vd.header["TESTKEY"] == "fixture"


def test_written_file_has_the_aas6sim_layout(tmp_path):
    vd = read_visibility(AAS6)
    path = write_visibility(tmp_path / "v.fits", vd, baseline_m=10.0)
    with fits.open(AAS6) as ref, fits.open(path) as new:
        r, n = ref["VISIBILITY"], new["VISIBILITY"]
        assert [(c.name, c.format, c.unit) for c in n.columns] == \
               [(c.name, c.format, c.unit) for c in r.columns]
        missing = {k for k in r.header if k not in ("COMMENT", "HISTORY")} - set(n.header)
        assert not missing
        for key in ("ANT1", "ANT2", "UVUNIT", "BASELINE", "RESTFRQ", "BANDWID", "TSYS",
                    "OBSRA", "OBSDEC", "OBJECT", "TELESCOP", "INSTRUME", "DATE-OBS",
                    "SIMULATD", "TESTKEY"):
            assert n.header[key] == r.header[key], key
        for col in ("TIME", "HA", "UU", "VV", "WW", "VISREAL", "VISIMAG", "WEIGHT"):
            np.testing.assert_array_equal(n.data[col], r.data[col])
    assert list(read_visibility(path).header["HISTORY"]) == ["fixture for tests/test_io.py"]


def test_aas6sim_reads_interferosim_file(tmp_path):
    aas6 = pytest.importorskip("aas6sim.visibility")
    vd = make(n_rows=4)
    data = aas6.read_visibility(str(write_visibility(tmp_path / "v.fits", vd)))
    np.testing.assert_array_equal(data.vis, vd.vis[:, 0])
    np.testing.assert_array_equal(data.weight, vd.weight[:, 0])
    assert data.simulated


# ---------------------------------------------------------------- headers, errors
def test_simulated_marker():
    assert is_simulated(base_header())
    assert not is_simulated(base_header(simulated=False))
    assert not is_simulated({})
    with pytest.raises(TypeError, match="unknown"):
        add_observation(base_header(), frequency=1.0)


def test_measured_data_stay_measured(tmp_path):
    vd = make(header={"SIMULATD": False})
    assert read_visibility(write_visibility(tmp_path / "v.fits", vd)).header["SIMULATD"] is False
    vd = make(header={})
    assert read_visibility(write_visibility(tmp_path / "w.fits", vd)).header["SIMULATD"] is True


def test_errors(tmp_path):
    vd = make(names=("A-B", "A-C"))
    with pytest.raises(ValueError, match="RESTFRQ"):
        write_visibility(tmp_path / "v.fits", vd, meta={"freq_hz": 1e9})
    with pytest.raises(ValueError, match="one baseline"):
        write_visibility(tmp_path / "v.fits", vd, baseline_m=10.0)
    bad = make(names=("A-B",))
    bad.baseline[0] = 3
    with pytest.raises(ValueError, match="outside"):
        write_visibility(tmp_path / "v.fits", bad)
    # a file without RESTFRQ needs the frequency from the caller
    path = write_visibility(tmp_path / "x.fits", make())
    with fits.open(path, mode="update") as hdul:
        del hdul[1].header["RESTFRQ"]
    with pytest.raises(ValueError, match="pass freq_hz"):
        read_visibility(path)
    assert read_visibility(path, freq_hz=1e9).freq_hz[0] == 1e9
    with pytest.raises(ValueError, match="channel"):
        read_visibility(path, freq_hz=[1e9, 2e9])
