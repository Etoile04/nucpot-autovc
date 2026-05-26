from typing import Any

_REF = {
  "U": {
    "BCC_gamma": {
      "lattice_constant": {"value": 3.47, "unit": "angstrom", "source": "Smirnov2014"},
      "cohesive_energy": {"value": -5.49, "unit": "eV/atom", "source": "Smirnov2014"},
      "elastic_constants_C11": {"value": 74.0, "unit": "GPa", "source": "Smirnov2014"},
      "elastic_constants_C12": {"value": 51.0, "unit": "GPa", "source": "Smirnov2014"},
      "elastic_constants_C44": {"value": 73.0, "unit": "GPa", "source": "Smirnov2014"}
    }
  },
  "Mo": {
    "BCC": {
      "lattice_constant": {"value": 3.147, "unit": "angstrom", "source": "exp"},
      "cohesive_energy": {"value": -6.82, "unit": "eV/atom", "source": "exp"},
      "elastic_constants_C11": {"value": 463.0, "unit": "GPa", "source": "exp"},
      "elastic_constants_C12": {"value": 161.0, "unit": "GPa", "source": "exp"},
      "elastic_constants_C44": {"value": 109.0, "unit": "GPa", "source": "exp"}
    }
  },
  "Zr": {
    "BCC": {
      "lattice_constant": {"value": 3.609, "unit": "angstrom", "source": "exp"},
      "cohesive_energy": {"value": -6.25, "unit": "eV/atom", "source": "exp"}
    }
  },
  "U-Mo": {
    "BCC_gamma": {
      "lattice_constant": {"value": 3.39, "unit": "angstrom", "source": "Smirnov2014"},
      "elastic_constants_C11": {"value": 140.0, "unit": "GPa", "source": "Smirnov2014"}
    }
  },
  "U-Zr": {
    "BCC_gamma": {
      "lattice_constant": {"value": 3.52, "unit": "angstrom", "source": "Landa2002"}
    }
  }
}

def get_reference_value(material, structure, property_name):
    m = _REF.get(material)
    if not m: return None
    s = m.get(structure)
    if not s: return None
    return s.get(property_name)

def list_available_properties():
    props = set()
    for m in _REF.values():
        for s in m.values():
            props.update(s.keys())
    return sorted(props)

def list_available_materials():
    return sorted(_REF.keys())
