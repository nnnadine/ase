# encoding: utf-8
"""nanoparticle.py - Window for setting up crystalline nanoparticles.
"""

from copy import copy
from gettext import gettext as _

import numpy as np

import ase
import ase.data
import ase.gui.ui as ui

# Delayed imports:
# ase.cluster.data

from ase.cluster.cubic import FaceCenteredCubic, BodyCenteredCubic, SimpleCubic
from ase.cluster.hexagonal import HexagonalClosedPacked, Graphite
from ase.cluster import wulff_construction
from ase.gui.widgets import Element, pybutton, helpbutton


introtext = _("""\
Create a nanoparticle either by specifying the number of layers, or using the
Wulff construction.  Please press the [Help] button for instructions on how to
specify the directions.
WARNING: The Wulff construction currently only works with cubic crystals!
""")

helptext = _("""
The nanoparticle module sets up a nano-particle or a cluster with a given
crystal structure.

1) Select the element, the crystal structure and the lattice constant(s).
   The [Get structure] button will find the data for a given element.

2) Choose if you want to specify the number of layers in each direction, or if
   you want to use the Wulff construction.  In the latter case, you must
   specify surface energies in each direction, and the size of the cluster.

How to specify the directions:
------------------------------

First time a direction appears, it is interpreted as the entire family of
directions, i.e. (0,0,1) also covers (1,0,0), (-1,0,0) etc.  If one of these
directions is specified again, the second specification overrules that specific
direction.  For this reason, the order matters and you can rearrange the
directions with the [Up] and [Down] keys.  You can also add a new direction,
remember to press [Add] or it will not be included.

Example: (1,0,0) (1,1,1), (0,0,1) would specify the {100} family of directions,
the {111} family and then the (001) direction, overruling the value given for
the whole family of directions.
""")

py_template_layers = """
import ase
%(import)s

surfaces = %(surfaces)s
layers = %(layers)s
lc = %(latconst)s
atoms = %(factory)s('%(element)s', surfaces, layers, latticeconstant=lc)

# OPTIONAL: Cast to ase.Atoms object, discarding extra information:
# atoms = ase.Atoms(atoms)
"""

py_template_wulff = """
import ase
from ase.cluster import wulff_construction

surfaces = %(surfaces)s
esurf = %(energies)s
lc = %(latconst)s
size = %(natoms)s  # Number of atoms
atoms = wulff_construction('%(element)s', surfaces, esurf,
                           size, '%(structure)s',
                           rounding='%(rounding)s', latticeconstant=lc)

# OPTIONAL: Cast to ase.Atoms object, discarding extra information:
# atoms = ase.Atoms(atoms)
"""


class SetupNanoparticle:
    "Window for setting up a nanoparticle."
    # Structures:  Abbreviation, name,
    # 4-index (boolean), two lattice const (bool), factory
    structure_data = (('fcc', _('Face centered cubic (fcc)'),
                       False, False, FaceCenteredCubic),
                      ('bcc', _('Body centered cubic (bcc)'),
                       False, False, BodyCenteredCubic),
                      ('sc', _('Simple cubic (sc)'),
                       False, False, SimpleCubic),
                      ('hcp', _('Hexagonal closed-packed (hcp)'),
                       True, True, HexagonalClosedPacked),
                      ('graphite', _('Graphite'),
                       True, True, Graphite))
    # NB:  HCP is broken!

    # A list of import statements for the Python window.
    import_names = {
        'fcc': 'from ase.cluster.cubic import FaceCenteredCubic',
        'bcc': 'from ase.cluster.cubic import BodyCenteredCubic',
        'sc': 'from ase.cluster.cubic import SimpleCubic',
        'hcp': 'from ase.cluster.hexagonal import HexagonalClosedPacked',
        'graphite': 'from ase.cluster.hexagonal import Graphite'}

    # Default layer specifications for the different structures.
    default_layers = {'fcc': [((1, 0, 0), 6),
                              ((1, 1, 0), 9),
                              ((1, 1, 1), 5)],
                      'bcc': [((1, 0, 0), 6),
                              ((1, 1, 0), 9),
                              ((1, 1, 1), 5)],
                      'sc': [((1, 0, 0), 6),
                             ((1, 1, 0), 9),
                             ((1, 1, 1), 5)],
                      'hcp': [((0, 0, 0, 1), 5),
                              ((1, 0, -1, 0), 5)],
                      'graphite': [((0, 0, 0, 1), 5),
                                   ((1, 0, -1, 0), 5)]}

    def __init__(self, gui):
        self.atoms = None
        self.no_update = True
        self.legal_element = False

        win = self.win = ui.Window(_('Nanoparticle'))
        win.add(ui.Text(introtext))

        self.element = Element('C', self.update)
        lattice_button = ui.Button(_('Get structure'),
                                   self.set_structure_data)
        self.elementinfo = ui.Label(' ')
        win.add(self.element)
        win.add(self.elementinfo)
        win.add(lattice_button)

        # The structure and lattice constant
        labels = []
        values = []
        self.needs_4index = {}
        self.needs_2lat = {}
        self.factory = {}
        for abbrev, name, n4, c, factory in self.structure_data:
            labels.append(name)
            values.append(abbrev)
            self.needs_4index[abbrev] = n4
            self.needs_2lat[abbrev] = c
            self.factory[abbrev] = factory
        self.structure = ui.ComboBox(labels, values, self.update_structure)
        win.add([_('Structure:'), self.structure])
        self.structure.active = False
        self.fourindex = self.needs_4index[values[0]]

        win.add([_('Lattice constant:  a ='),
                 ui.SpinBox(3.0, 0.0, 1000.0, 0.01, self.update),
                 ' c =',
                 ui.SpinBox(3.0, 0.0, 1000.0, 0.01, self.update)])

        # Choose specification method
        self.method = ui.ComboBox(
            [_('Layer specification'), _('Wulff construction')],
            ['layers', 'wulff'],
            self.update_gui_method)
        win.add([_('Method: '), self.method])

        self.layerlabel = ui.Label('Missing text')  # Filled in later
        win.add(self.layerlabel)
        self.direction_table_rows = ui.Rows()
        win.add(self.direction_table_rows)
        self.default_direction_table()

        win.add(_('Add new direction:'))
        self.new_direction_and_size_rows = ui.Rows()
        win.add(self.new_direction_and_size_rows)
        self.update_new_direction_and_size_stuff()

        # Information
        win.add(_('Information about the created cluster:'))
        self.info = [_('Number of atoms: '),
                     ui.Label('-'),
                     _('   Approx. diameter: '),
                     ui.Label('-')]
        win.add(self.info)

        # Finalize setup
        self.update_structure()
        self.update_gui_method()
        self.no_update = False

        self.auto = ui.CheckButton(_('Automatic Apply'))
        win.add(self.auto)

        win.add([pybutton(_('Creating a nanoparticle.'), self, self.makeatoms),
                 helpbutton(helptext),
                 ui.Button(_('Apply'), self.apply),
                 ui.Button(_('OK'), self.ok)])

        self.gui = gui
        self.python = None

    def default_direction_table(self, widget=None):
        'Set default directions and values for the current crystal structure.'
        self.direction_table = []
        self.direction_table_rows.clear()
        struct = self.structure.value
        for direction, layers in self.default_layers[struct]:
            self.add_direction(direction, layers, 1.0)

    def add_direction(self, direction, layers, energy):
        i = len(self.direction_table)
        self.direction_table.append((direction, layers, energy))

        if self.method.value == 'wulff':
            spin = ui.SpinBox(energy, 0.0, 1000.0, 0.1, self.update)
        else:
            spin = ui.SpinBox(layers, 1, 100, 1, self.update)

        up = ui.Button(_('Up'), self.row_swap_next, i - 1)
        down = ui.Button(_('Down'), self.row_swap_next, i)
        delete = ui.Button(_('Delete'), self.row_delete, i)

        self.direction_table_rows.add([str(direction) + ':',
                                       spin, up, down, delete])
        up.active = i > 0
        down.active = False
        delete.active = i > 0

        if i > 0:
            down, delete = self.direction_table_rows[-2][3:]
            down.active = True
            delete.active = True

        self.update()

    def update_new_direction_and_size_stuff(self):
        if self.structure.value in ['hcp', 'graphite']:
            n = 4
        else:
            n = 3

        self.new_direction_and_size_rows.clear()

        row = ['(']
        for i in range(n):
            if i > 0:
                row.append(',')
            row.append(ui.SpinBox(0, -100, 100, 1))
        row.append('):')

        if self.method.value == 'wulff':
            row.append(ui.SpinBox(1.0, 0.0, 1000.0, 0.1))
        else:
            row.append(ui.SpinBox(5, 1, 100, 1))

        row.append(ui.Button(_('Add'), self.row_add))

        self.new_direction_and_size_rows.add(row)

        if self.method.value == 'wulff':
            # Extra widgets for the Wulff construction
            ...

        """
        self.wulffbox = ui.VBox()
        pack(vbox, self.wulffbox)
        label = ui.Label(_('Particle size: '))
        self.size_n_radio = ui.RadioButton(None, _('Number of atoms: '))
        self.size_n_radio.set_active(True)
        self.size_n_adj = ui.Adjustment(100, 1, 100000, 1)
        self.size_n_spin = ui.SpinButton(self.size_n_adj, 0, 0)
        self.size_dia_radio = ui.RadioButton(self.size_n_radio,
                                              _('Volume: '))
        self.size_dia_adj = ui.Adjustment(1.0, 0, 100.0, 0.1)
        self.size_dia_spin = ui.SpinButton(self.size_dia_adj, 10.0, 2)
        pack(self.wulffbox, [label, self.size_n_radio, self.size_n_spin,
                    ui.Label('   '), self.size_dia_radio, self.size_dia_spin,
                    ui.Label(_(u'Å³'))])
        self.size_n_radio.connect('toggled', self.update_gui_size)
        self.size_dia_radio.connect('toggled', self.update_gui_size)
        self.size_n_adj.connect('value-changed', self.update_size_n)
        self.size_dia_adj.connect('value-changed', self.update_size_dia)
        label = ui.Label(_('Rounding: If exact size is not possible, '
                            'choose the size'))
        pack(self.wulffbox, [label])
        self.round_above = ui.RadioButton(None, _('above  '))
        self.round_below = ui.RadioButton(self.round_above, _('below  '))
        self.round_closest = ui.RadioButton(self.round_above, _('closest  '))
        self.round_closest.set_active(True)
        butbox = ui.HButtonBox()
        self.smaller_button = ui.Button(_('Smaller'))
        self.larger_button = ui.Button(_('Larger'))
        self.smaller_button.connect('clicked', self.wulff_smaller)
        self.larger_button.connect('clicked', self.wulff_larger)
        pack(butbox, [self.smaller_button, self.larger_button])
        buts = [self.round_above, self.round_below, self.round_closest]
        for b in buts:
            b.connect('toggled', self.update)
        buts.append(butbox)
        pack(self.wulffbox, buts, end=True)
        """

    def update_structure(self, widget=None):
        'Called when the user changes the structure.'
        s = self.structure.value
        if s != self.old_structure:
            old4 = self.fourindex
            self.fourindex = self.needs_4index[s]
            if self.fourindex != old4:
                # The table of directions is invalid.
                self.default_direction_table()
            self.old_structure = s
            if self.needs_2lat[s]:
                self.lattice_label_c.show()
                self.lattice_box_c.show()
            else:
                self.lattice_label_c.hide()
                self.lattice_box_c.hide()
            if self.fourindex:
                self.newdir_label[3].show()
                self.newdir_box[3].show()
            else:
                self.newdir_label[3].hide()
                self.newdir_box[3].hide()
        self.update()

    def update_gui_method(self, widget=None):
        'Switch between layer specification and Wulff construction.'
        self.update_direction_table()
        if self.method.value == 'wulff':
            self.wulffbox.show()
            self.layerlabel.set_text(_('Surface energies (as energy/area, '
                                       'NOT per atom):'))
            self.newdir_layers_box.hide()
            self.newdir_esurf_box.show()
        else:
            self.wulffbox.hide()
            self.layerlabel.set_text(_('Number of layers:'))
            self.newdir_layers_box.show()
            self.newdir_esurf_box.hide()
        self.update()

    def wulff_smaller(self, widget=None):
        'Make a smaller Wulff construction.'
        n = len(self.atoms)
        self.size_n_radio.set_active(True)
        self.size_n_adj.value = n-1
        self.round_below.set_active(True)
        self.apply()

    def wulff_larger(self, widget=None):
        'Make a larger Wulff construction.'
        n = len(self.atoms)
        self.size_n_radio.set_active(True)
        self.size_n_adj.value = n+1
        self.round_above.set_active(True)
        self.apply()

    def row_add(self, widget=None):
        'Add a row to the list of directions.'
        if self.fourindex:
            n = 4
        else:
            n = 3
        idx = tuple( [int(a.value) for a in self.newdir_index[:n]] )
        if not np.array(idx).any():
            oops(_('At least one index must be non-zero'))
            return
        if n == 4 and np.array(idx)[:3].sum() != 0:
            oops(_('Invalid hexagonal indices',
                 'The sum of the first three numbers must be zero'))
            return
        adj1 = ui.Adjustment(self.newdir_layers.value, -100, 100, 1)
        adj2 = ui.Adjustment(self.newdir_esurf.value, -1000.0, 1000.0, 0.1)
        adj1.connect('value-changed', self.update)
        adj2.connect('value-changed', self.update)
        self.direction_table.append([idx, adj1, adj2])
        self.update_direction_table()

    def row_delete(self, row):
        del self.direction_table[row]
        self.update_direction_table()

    def row_swap_next(self, widget, row):
        dt = self.direction_table
        dt[row], dt[row+1] = dt[row+1], dt[row]
        self.update_direction_table()

    def update_gui_size(self, widget=None):
        'Update gui when the cluster size specification changes.'
        self.size_n_spin.set_sensitive(self.size_n_radio.get_active())
        self.size_dia_spin.set_sensitive(self.size_dia_radio.get_active())

    def update_size_n(self, widget=None):
        if not self.size_n_radio.get_active():
            return
        at_vol = self.get_atomic_volume()
        dia = 2.0 * (3 * self.size_n_adj.value * at_vol / (4 * np.pi))**(1.0/3)
        self.size_dia_adj.value = dia
        self.update()

    def update_size_dia(self, widget=None):
        if not self.size_dia_radio.get_active():
            return
        at_vol = self.get_atomic_volume()
        n = round(np.pi / 6 * self.size_dia_adj.value**3 / at_vol)
        self.size_n_adj.value = n
        self.update()

    def update(self, *args):
        if self.no_update:
            return
        self.update_element()
        if self.auto.get_active():
            self.makeatoms()
            if self.atoms is not None:
                self.gui.new_atoms(self.atoms)
        else:
            self.clearatoms()
        self.makeinfo()

    def set_structure_data(self, *args):
        'Called when the user presses [Get structure].'
        if not self.update_element():
            oops(_('Invalid element.'))
            return
        z = ase.data.atomic_numbers[self.legal_element]
        ref = ase.data.reference_states[z]
        if ref is None:
            structure = None
        else:
            structure = ref['symmetry']

        if ref is None or not structure in self.list_of_structures:
            oops(_('Unsupported or unknown structure',
                   'Element = %s,  structure = %s' % (self.legal_element,
                                                      structure)))
            return
        for i, s in enumerate(self.list_of_structures):
            if structure == s:
                self.structure.set_active(i)
        a = ref['a']
        self.lattice_const_a.set_value(a)
        self.fourindex = self.needs_4index[structure]
        if self.fourindex:
            try:
                c = ref['c']
            except KeyError:
                c = ref['c/a'] * a
            self.lattice_const_c.set_value(c)
            self.lattice_label_c.show()
            self.lattice_box_c.show()
        else:
            self.lattice_label_c.hide()
            self.lattice_box_c.hide()

    def makeatoms(self, *args):
        'Make the atoms according to the current specification.'
        if not self.update_element():
            self.clearatoms()
            self.makeinfo()
            return False
        assert self.legal_element is not None
        struct = self.list_of_structures[self.structure.get_active()]
        if self.needs_2lat[struct]:
            # a and c lattice constants
            lc = {'a': self.lattice_const_a.value,
                  'c': self.lattice_const_c.value}
            lc_str = str(lc)
        else:
            lc = self.lattice_const_a.value
            lc_str = '%.5f' % (lc,)
        if self.method.get_active() == 0:
            # Layer-by-layer specification
            surfaces = [x[0] for x in self.direction_table]
            layers = [int(x[1].value) for x in self.direction_table]
            self.atoms = self.factory[struct](self.legal_element, copy(surfaces),
                                              layers, latticeconstant=lc)
            imp = self.import_names[struct]
            self.pybut.python = py_template_layers % {'import': imp,
                                                      'element': self.legal_element,
                                                      'surfaces': str(surfaces),
                                                      'layers': str(layers),
                                                      'latconst': lc_str,
                                                      'factory': imp.split()[-1]
                                                      }
        else:
            # Wulff construction
            assert self.method.get_active() == 1
            surfaces = [x[0] for x in self.direction_table]
            surfaceenergies = [x[2].value for x in self.direction_table]
            self.update_size_dia()
            if self.round_above.get_active():
                rounding = 'above'
            elif self.round_below.get_active():
                rounding = 'below'
            elif self.round_closest.get_active():
                rounding = 'closest'
            else:
                raise RuntimeError('No rounding!')
            self.atoms = wulff_construction(self.legal_element, surfaces,
                                            surfaceenergies,
                                            self.size_n_adj.value,
                                            self.factory[struct],
                                            rounding, lc)
            self.pybut.python = py_template_wulff % {'element': self.legal_element,
                                                     'surfaces': str(surfaces),
                                                     'energies': str(surfaceenergies),
                                                     'latconst': lc_str,
                                                     'natoms': self.size_n_adj.value,
                                                     'structure': struct,
                                                     'rounding': rounding
                                                      }
        self.makeinfo()

    def clearatoms(self):
        self.atoms = None
        self.pybut.python = None

    def get_atomic_volume(self):
        s = self.list_of_structures[self.structure.get_active()]
        a = self.lattice_const_a.value
        c = self.lattice_const_c.value
        if s == 'fcc':
            return a**3 / 4
        elif s == 'bcc':
            return a**3 / 2
        elif s == 'sc':
            return a**3
        elif s == 'hcp':
            return np.sqrt(3.0)/2 * a * a * c / 2
        elif s == 'graphite':
            return np.sqrt(3.0)/2 * a * a * c / 4
        else:
            raise RuntimeError('Unknown structure: '+s)

    def makeinfo(self):
        """Fill in information field about the atoms.

        Also turns the Wulff construction buttons [Larger] and
        [Smaller] on and off.
        """
        if self.atoms is None:
            self.natoms_label.set_label('-')
            self.dia1_label.set_label('-')
            self.smaller_button.set_sensitive(False)
            self.larger_button.set_sensitive(False)
        else:
            self.natoms_label.set_label(str(len(self.atoms)))
            at_vol = self.get_atomic_volume()
            dia = 2 * (3 * len(self.atoms) * at_vol / (4 * np.pi))**(1.0/3.0)
            self.dia1_label.set_label(_(u'%.1f Å') % (dia,))
            self.smaller_button.set_sensitive(True)
            self.larger_button.set_sensitive(True)

    def apply(self, *args):
        self.makeatoms()
        if self.atoms is not None:
            self.gui.new_atoms(self.atoms)
            return True
        else:
            oops(_('No valid atoms.'),
                 _('You have not (yet) specified a consistent set of '
                   'parameters.'))
            return False

    def ok(self, *args):
        if self.apply():
            self.destroy()
