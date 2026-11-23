# tests/test_properties.py -- property-based tests (Hypothesis) of interferosim
"""Property-based tests with Hypothesis.

Instead of single hand-picked values, Hypothesis draws many random inputs
from a described range and checks a property that must hold for all of
them; a counterexample is shrunk to the simplest failing input.

Properties checked:

* spectral lines: frequency -> radio velocity -> frequency is the identity;
* sky components: Hermitian symmetry V(-u, -v) = conj V(u, v) of the
  visibility of a real sky, |V| <= flux (equality for a point source),
  monotonic decrease of a Gaussian along a ray in the uv-plane, and the
  JSON round trip ``component_from_dict(c.to_dict()) == c``;
* geometry: the sky basis is orthonormal and right-handed, (u, v, w) is
  linear in the baseline (reversed baseline -> negated uvw);
* receive path: quantisation efficiency in (0, 1] and not decreasing with
  the number of bits; the Van Vleck correction is odd, monotonic and
  bounded; the image rejection ratio is not negative and even in the
  phase error;
* sensitivity: coherence factor in (0, 1] and decreasing with the phase
  rms.

Version 1.0.4 (2026-11-23): first version.
"""

import math

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from interferosim.constants import LINES
from interferosim.instrument.sensitivity import coherence_factor
from interferosim.observation.geometry import sky_basis, uvw
from interferosim.signal.baseband import (image_rejection_db, quantization_efficiency,
                                          van_vleck_1bit)
from interferosim.sky.components import (DiscSource, GaussianSource, PointSource,
                                         component_from_dict)
from interferosim.sky.spectra import frequency_from_velocity, radio_velocity_kms

# numpy/scipy calls can be slow on their first use; no deadline per example
settings.register_profile("interferosim", deadline=None, max_examples=100,
                          suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("interferosim")

# ---------------------------------------------------------------- strategies
finite = dict(allow_nan=False, allow_infinity=False)
offsets = st.floats(-1.0, 1.0, **finite)                 # deg from the phase centre
fluxes = st.floats(0.01, 1e5, **finite)                  # Jy
uv = st.floats(-5e4, 5e4, **finite)                      # wavelengths
names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=1, max_size=12)


@st.composite
def components(draw):
    """A point source, an elliptical Gaussian or a uniform disc."""
    kind = draw(st.sampled_from(["point", "gauss", "disc"]))
    common = dict(name=draw(names), dx_deg=draw(offsets), dy_deg=draw(offsets),
                  flux_jy=draw(fluxes))
    if kind == "point":
        return PointSource(**common)
    if kind == "gauss":
        return GaussianSource(**common, fwhm_x_deg=draw(st.floats(0.001, 2.0, **finite)),
                              fwhm_y_deg=draw(st.floats(0.001, 2.0, **finite)),
                              pa_deg=draw(st.floats(-180.0, 180.0, **finite)))
    # uniform disc: analytic visibility 2 J1(x)/x (no numerical Hankel transform)
    return DiscSource(**common, diameter_deg=draw(st.floats(0.001, 1.0, **finite)))


# ---------------------------------------------------------------- spectra
@given(v_kms=st.floats(-1000.0, 1000.0, **finite), line=st.sampled_from(sorted(LINES)))
def test_velocity_frequency_roundtrip(v_kms, line):
    f0 = LINES[line]
    f = frequency_from_velocity(v_kms, f0)
    assert float(radio_velocity_kms(f, f0)) == pytest.approx(v_kms, abs=1e-6)


# ---------------------------------------------------------------- sky components
@given(c=components(), u=uv, v=uv)
def test_visibility_is_hermitian(c, u, v):
    """A real brightness distribution has V(-u, -v) = conj(V(u, v))."""
    a = complex(c.visibility(u, v))
    b = complex(c.visibility(-u, -v))
    assert b == pytest.approx(a.conjugate(), rel=1e-9, abs=1e-9 * c.flux_jy)


@given(c=components(), u=uv, v=uv)
def test_visibility_amplitude_bounded_by_flux(c, u, v):
    amp = abs(complex(c.visibility(u, v)))
    assert amp <= c.flux_jy * (1 + 1e-9)
    if isinstance(c, PointSource):
        assert amp == pytest.approx(c.flux_jy, rel=1e-9)
    assert complex(c.visibility(0.0, 0.0)) == pytest.approx(c.flux_jy, rel=1e-9)


@given(fwhm=st.floats(0.001, 2.0, **finite), pa=st.floats(-180.0, 180.0, **finite),
       u=uv, v=uv, k1=st.floats(0.0, 1.0, **finite), k2=st.floats(0.0, 1.0, **finite))
def test_gaussian_amplitude_decreases_along_a_ray(fwhm, pa, u, v, k1, k2):
    g = GaussianSource("g", 0.0, 0.0, 1.0, fwhm_x_deg=fwhm, fwhm_y_deg=0.5 * fwhm, pa_deg=pa)
    lo, hi = sorted((k1, k2))
    a_lo = abs(complex(g.visibility(lo * u, lo * v)))
    a_hi = abs(complex(g.visibility(hi * u, hi * v)))
    assert a_hi <= a_lo + 1e-12


@given(c=components())
def test_component_dict_roundtrip(c):
    assert component_from_dict(c.to_dict()) == c


# ---------------------------------------------------------------- geometry
@given(dec=st.floats(-90.0, 90.0, **finite), gha=st.floats(0.0, 360.0, **finite))
def test_sky_basis_orthonormal_right_handed(dec, gha):
    s0, e_e, e_n = sky_basis(dec, gha)
    m = np.stack([s0, e_e, e_n])
    assert np.allclose(m @ m.T, np.eye(3), atol=1e-12)
    # s0 points to the source, e_E east, e_N north: e_E x e_N = s0
    assert np.allclose(np.cross(e_e, e_n), s0, atol=1e-12)


@given(b=st.lists(st.floats(-2e4, 2e4, **finite), min_size=3, max_size=3),
       dec=st.floats(-89.0, 89.0, **finite), gha=st.floats(0.0, 360.0, **finite),
       scale=st.floats(0.1, 10.0, **finite))
def test_uvw_is_linear_in_the_baseline(b, dec, gha, scale):
    lam = 0.21
    base = uvw(b, dec, gha, lam)
    assert np.allclose(uvw([-x for x in b], dec, gha, lam), -base, atol=1e-6)
    assert np.allclose(uvw([scale * x for x in b], dec, gha, lam), scale * base,
                       rtol=1e-9, atol=1e-6)
    # the length of the baseline is kept: |uvw| = |b| / lambda
    assert np.linalg.norm(base) == pytest.approx(np.linalg.norm(b) / lam, rel=1e-9, abs=1e-6)


# ---------------------------------------------------------------- receive path
@given(bits=st.integers(1, 7))
def test_quantization_efficiency_bounded_and_not_decreasing(bits):
    e1 = quantization_efficiency(bits)
    e2 = quantization_efficiency(bits + 1)
    assert 0.0 < e1 <= 1.0 and 0.0 < e2 <= 1.0
    assert e2 >= e1 - 1e-12


@given(r1=st.floats(-1.0, 1.0, **finite), r2=st.floats(-1.0, 1.0, **finite))
def test_van_vleck_odd_monotonic_bounded(r1, r2):
    a, b = float(van_vleck_1bit(r1)), float(van_vleck_1bit(r2))
    assert -1.0 <= a <= 1.0
    assert float(van_vleck_1bit(-r1)) == pytest.approx(-a, abs=1e-15)
    if r1 <= r2:
        assert a <= b + 1e-15
    # the true correlation is never smaller in magnitude than the 1-bit one
    assert abs(a) >= abs(r1) - 1e-15


@given(gain_db=st.floats(-3.0, 3.0, **finite), phase_deg=st.floats(-30.0, 30.0, **finite))
def test_image_rejection_not_negative_and_even_in_phase(gain_db, phase_deg):
    irr = image_rejection_db(gain_db, phase_deg)
    assert irr >= 0.0
    other = image_rejection_db(gain_db, -phase_deg)
    assert other == irr or other == pytest.approx(irr, rel=1e-12)


# ---------------------------------------------------------------- sensitivity
@given(s1=st.floats(0.0, 10.0, **finite), s2=st.floats(0.0, 10.0, **finite))
def test_coherence_factor_bounded_and_decreasing(s1, s2):
    c1, c2 = float(coherence_factor(s1)), float(coherence_factor(s2))
    assert 0.0 < c1 <= 1.0
    if s1 <= s2:
        assert c2 <= c1
    assert c1 == pytest.approx(math.exp(-0.5 * s1 * s1), rel=1e-12, abs=1e-300)
