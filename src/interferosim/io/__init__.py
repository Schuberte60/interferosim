# src/interferosim/io/__init__.py -- sub-package interferosim.io
"""Input/output: FITS files (maps, visibilities, spectra, time series, UVFITS), taken over from aas6sim 1.1.0.

Modules:

headers      common header keywords (ORIGIN, SIMULATD, observation keys)
visibility   VisData as FITS binary table VISIBILITY (format of aas6sim 1.3.1,
             extended by channels and baselines)

Maps, cross-spectra cubes, time series and UVFITS are not taken over yet;
``aas6sim`` writes them.

Version 0.1.0: empty skeleton, filled in the migration steps.
Version 1.0.6 (2026-11-25): headers and visibility (requirement F-DAT-2).
"""

from .headers import SIM_KEYWORD, add_observation, base_header, is_simulated
from .visibility import read_visibility, write_visibility

__all__: list[str] = ["SIM_KEYWORD", "add_observation", "base_header", "is_simulated",
                      "read_visibility", "write_visibility"]
