import os
import platform
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from unit_trace.models import ProjectValidationError
from unit_trace.units import make_registry, resolve_unit
from unit_trace.profile import get_profile


class UnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = make_registry()

    def test_conversion_and_composites(self):
        r = self.registry
        self.assertAlmostEqual(r.Quantity(1, resolve_unit('cm**2', r)).to(resolve_unit('m**2', r)).magnitude, .0001)
        self.assertEqual(str(resolve_unit('m/(s**2)', r).dimensionality), '[length] / [time] ** 2')
        self.assertTrue(resolve_unit('1', r).dimensionless)
        for text in ['m**-12', 'm**+12', 'kg/m**3', 'm**2/s', '(m*m)**12']:
            resolve_unit(text, r)

    def test_whitelist_is_case_sensitive(self):
        for symbol in ['m','cm','mm','um','nm','km','s','ms','us','min','h','kg','g','mg','L','mL','mol','mmol','A','mA','V','mV','ohm','kohm','N','Pa','kPa','MPa','J','kJ','W','mW','Hz','rad']:
            resolve_unit(symbol, self.registry)
        for text in ['M', 'meter', 'degC', 'delta_degC', 'K', 'degF', 'cm²', 'μm', 'unknown']:
            with self.assertRaises(ProjectValidationError):
                resolve_unit(text, self.registry)

    def test_injection_and_limits(self):
        for text in ['m;s', 'm\ns', 'x = m', 'm(1)', '[m]', 'm**13', 'm**1.5', 'm**s', 'm**2**2', '(m**2)**2', '(m*m*m)**12', '('*9+'m'+')'*9, '*'.join(['m']*17), 'm'+' '*64, '']:
            with self.subTest(text=text):
                with self.assertRaises(ProjectValidationError):
                    resolve_unit(text, self.registry)

    def test_non_ascii_units_offer_explicit_ascii_alternatives(self):
        for text, suggestion in [('cm²', 'cm**2'), ('μm', 'um')]:
            with self.assertRaises(ProjectValidationError) as caught:
                resolve_unit(text, self.registry)
            self.assertIn(suggestion, caught.exception.issues[0].message)

    def test_environment_definitions_are_not_loaded_and_no_disk_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            custom = Path(directory) / 'units.txt'
            custom.write_text('injected_unit = 2 * meter', encoding='utf-8')
            with patch.dict(os.environ, {'PINT_DEFAULT_REGISTRY': str(custom), 'PINT_UNIT_DEFINITIONS': str(custom), 'XDG_CACHE_HOME': directory}):
                r = make_registry()
                self.assertEqual(r.Quantity(1, resolve_unit('cm', r)).to(resolve_unit('m', r)).magnitude, .01)
                with self.assertRaises(ProjectValidationError):
                    resolve_unit('injected_unit', r)
                self.assertIsNone(r._diskcache)
                self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['units.txt'])

    def test_profile_has_actual_dependency_versions_and_resource_hashes(self):
        data = get_profile().to_json()
        self.assertEqual(data['pintVersion'], '0.25.2')
        self.assertEqual(data['pythonVersion'], platform.python_version())
        self.assertEqual(data['pythonVersion'].split('.')[:2], ['3', '12'])
        self.assertEqual(data['dependencies']['flexparser'], '0.4')
        self.assertEqual(set(data['dependencies']), {'Pint', 'flexcache', 'flexparser', 'platformdirs', 'typing_extensions'})
        self.assertIn('pint/default_en.txt', data['definitionHashes'])
        self.assertIn('pint/constants_en.txt', data['definitionHashes'])
        for key, value in data['definitionHashes'].items():
            self.assertNotIn(':', key)
            self.assertRegex(value, r'^[0-9a-f]{64}$')
