#!/usr/bin/env cctbx.python

#
#  Copyright (C) (2013) STFC Rutherford Appleton Laboratory, UK.
#
#  Author: David Waterman.
#
#  This code is distributed under the BSD license, a copy of which is
#  included in the root directory of this package.
#

"""
Simple tests of the new reflection manager in comparison with the old version.

"""

# Python and cctbx imports
from __future__ import division
import sys
from math import pi
from scitbx import matrix
from libtbx.phil import parse
from libtbx.test_utils import approx_equal

# Get modules to build models and minimiser using PHIL
from dials.test.algorithms.refinement import setup_geometry
from dials.test.algorithms.refinement import setup_minimiser

# We will set up a mock scan and a mock experiment list
from dxtbx.model.scan import scan_factory
from dials.model.experiment.experiment_list import ExperimentList, Experiment

# Model parameterisations
from dials.algorithms.refinement.parameterisation.detector_parameters import \
    DetectorParameterisationSinglePanel
from dials.algorithms.refinement.parameterisation.beam_parameters import \
    BeamParameterisationOrientation
from dials.algorithms.refinement.parameterisation.crystal_parameters import \
    CrystalOrientationParameterisation, CrystalUnitCellParameterisation

# Symmetry constrained parameterisation for the unit cell
from cctbx.uctbx import unit_cell
from rstbx.symmetry.constraints.parameter_reduction import \
    symmetrize_reduce_enlarge

# Reflection prediction
from dials.algorithms.spot_prediction import IndexGenerator
from dials.algorithms.refinement.prediction import ScansRayPredictor
from dials.algorithms.spot_prediction import ray_intersection
from cctbx.sgtbx import space_group, space_group_symbols

# Parameterisation of the prediction equation
from dials.algorithms.refinement.parameterisation.prediction_parameters import \
    XYPhiPredictionParameterisation

# Imports for the target function
from dials.algorithms.refinement.target import LeastSquaresPositionalResidualWithRmsdCutoff
from dials.algorithms.refinement.reflection_manager import ReflectionManager

# Import helper functions
from dials.algorithms.refinement.refinement_helpers import print_model_geometry

#############################
# Setup experimental models #
#############################

args = sys.argv[1:]
master_phil = parse("""
    include scope dials.test.algorithms.refinement.geometry_phil
    include scope dials.test.algorithms.refinement.minimiser_phil
    """, process_includes=True)

models = setup_geometry.Extract(master_phil, cmdline_args = args,
                                 local_overrides="geometry.parameters.random_seed = 1")

crystal1 = models.crystal

models = setup_geometry.Extract(master_phil, cmdline_args = args,
                                 local_overrides="geometry.parameters.random_seed = 2")

mydetector = models.detector
mygonio = models.goniometer
crystal2 = models.crystal
mybeam = models.beam

# Build a mock scan for a 180 degree sweep
sf = scan_factory()
myscan = sf.make_scan(image_range = (1,1800),
                      exposure_times = 0.1,
                      oscillation = (0, 0.1),
                      epochs = range(1800),
                      deg = True)
sweep_range = myscan.get_oscillation_range(deg=False)
temp = myscan.get_oscillation(deg=False)
im_width = temp[1] - temp[0]
assert sweep_range == (0., pi)
assert approx_equal(im_width, 0.1 * pi / 180.)

# Build an experiment list
experiments = ExperimentList()
experiments.append(Experiment(
      beam=mybeam, detector=mydetector, goniometer=mygonio,
      scan=myscan, crystal=crystal1, imageset=None))
experiments.append(Experiment(
      beam=mybeam, detector=mydetector, goniometer=mygonio,
      scan=myscan, crystal=crystal2, imageset=None))

assert len(experiments.detectors()) == 1

##########################################################
# Parameterise the models (only for perturbing geometry) #
##########################################################

det_param = DetectorParameterisationSinglePanel(mydetector,
  experiments.indices(mydetector))
s0_param = BeamParameterisationOrientation(mybeam, mygonio,
  experiments.indices(mybeam))
xl1o_param = CrystalOrientationParameterisation(crystal1,
  experiments.indices(crystal1))
xl1uc_param = CrystalUnitCellParameterisation(crystal1,
  experiments.indices(crystal1))
xl2o_param = CrystalOrientationParameterisation(crystal2,
  experiments.indices(crystal2))
xl2uc_param = CrystalUnitCellParameterisation(crystal2,
  experiments.indices(crystal2))

# Fix beam to the X-Z plane (imgCIF geometry)
s0_param.set_fixed([True, False])

################################
# Apply known parameter shifts #
################################

# shift detector by 2.0 mm each translation and 5 mrad each rotation
det_p_vals = det_param.get_param_vals()
p_vals = [a + b for a, b in zip(det_p_vals,
                                [2.0, 2.0, 2.0, 5., 5., 5.])]
det_param.set_param_vals(p_vals)

# shift beam by 2 mrad in free axis
s0_p_vals = s0_param.get_param_vals()
p_vals = list(s0_p_vals)
p_vals[0] += 2.
s0_param.set_param_vals(p_vals)

# rotate crystal a bit (=2 mrad each rotation)
xlo_p_vals = []
for xlo in (xl1o_param, xl2o_param):
  p_vals = xlo.get_param_vals()
  xlo_p_vals.append(p_vals)
  new_p_vals = [a + b for a, b in zip(p_vals, [2., 2., 2.])]
  xlo.set_param_vals(new_p_vals)

# change unit cell a bit (=0.1 Angstrom length upsets, 0.1 degree of
# gamma angle)
xluc_p_vals = []
for xluc, xl in ((xl1uc_param, crystal1),((xl2uc_param, crystal2))):
  p_vals = xluc.get_param_vals()
  xluc_p_vals.append(p_vals)
  cell_params = xl.get_unit_cell().parameters()
  cell_params = [a + b for a, b in zip(cell_params, [0.1, 0.1, 0.1, 0.0,
                                                     0.0, 0.1])]
  new_uc = unit_cell(cell_params)
  newB = matrix.sqr(new_uc.fractionalization_matrix()).transpose()
  S = symmetrize_reduce_enlarge(xl.get_space_group())
  S.set_orientation(orientation=newB)
  X = tuple([e * 1.e5 for e in S.forward_independent_parameters()])
  xluc.set_param_vals(X)

#############################
# Generate some reflections #
#############################

print "Reflections will be generated with the following geometry:"
print mybeam
print mydetector
print crystal1
print crystal2

# All indices in a 2.0 Angstrom sphere for crystal1
resolution = 2.0
index_generator = IndexGenerator(crystal1.get_unit_cell(),
                space_group(space_group_symbols(1).hall()).type(), resolution)
indices1 = index_generator.to_array()

# All indices in a 2.0 Angstrom sphere for crystal2
resolution = 2.0
index_generator = IndexGenerator(crystal2.get_unit_cell(),
                space_group(space_group_symbols(1).hall()).type(), resolution)
indices2 = index_generator.to_array()

# Build a reflection predictor
ref_predictor = ScansRayPredictor(experiments, sweep_range)

obs_refs1 = ref_predictor.predict(indices1, experiment_id=0)
obs_refs2 = ref_predictor.predict(indices2, experiment_id=1)

print "Total number of reflections excited for crystal1", len(obs_refs1)
print "Total number of reflections excited for crystal2", len(obs_refs2)

# Invent some variances for the centroid positions of the simulated data
im_width = 0.1 * pi / 180.
px_size = mydetector[0].get_pixel_size()
var_x = (px_size[0] / 2.)**2
var_y = (px_size[1] / 2.)**2
var_phi = (im_width / 2.)**2

obs_refs1 = ray_intersection(experiments[0].detector, obs_refs1)
obs_refs2 = ray_intersection(experiments[1].detector, obs_refs2)

for ref in obs_refs1:

  # set the 'observed' centroids
  ref.centroid_position = ref.image_coord_mm + (ref.rotation_angle, )

  # set the centroid variance
  ref.centroid_variance = (var_x, var_y, var_phi)

  # set the frame number, calculated from rotation angle
  ref.frame_number = myscan.get_image_index_from_angle(
      ref.rotation_angle, deg=False)

  # ensure the crystal number is set to zero (should be by default)
  ref.crystal = 0

for ref in obs_refs2:

  # set the 'observed' centroids
  ref.centroid_position = ref.image_coord_mm + (ref.rotation_angle, )

  # set the centroid variance
  ref.centroid_variance = (var_x, var_y, var_phi)

  # set the frame number, calculated from rotation angle
  ref.frame_number = myscan.get_image_index_from_angle(
      ref.rotation_angle, deg=False)

  # ensure the crystal number is set to one
  ref.crystal = 1

print "Total number of observations made for crystal1", len(obs_refs1)
print "Total number of observations made for crystal2", len(obs_refs2)

# concatenate reflection lists
obs_refs = obs_refs1.concatenate(obs_refs2)

###############################
# Undo known parameter shifts #
###############################

s0_param.set_param_vals(s0_p_vals)
det_param.set_param_vals(det_p_vals)
xl1o_param.set_param_vals(xlo_p_vals[0])
xl2o_param.set_param_vals(xlo_p_vals[1])
xl1uc_param.set_param_vals(xluc_p_vals[0])
xl2uc_param.set_param_vals(xluc_p_vals[1])

#####################################
# Select reflections for refinement #
#####################################

reflections = obs_refs.to_table(centroid_is_mm=True)
from copy import deepcopy
old_reflections = deepcopy(reflections)

# make a new ReflectionManager
refman = ReflectionManager(reflections, experiments, verbosity=2, iqr_multiplier=None)

# make a new reflection predictor
from dials.algorithms.refinement.prediction import ExperimentsPredictor
ref_predictor = ExperimentsPredictor(experiments)

#import pprint
#pp = pprint.PrettyPrinter()
#for i in range(2):
#  pp.pprint(old_reflections[i])

#ref_predictor.predict(reflections)

from dials.algorithms.refinement.parameterisation.prediction_parameters_new import \
    XYPhiPredictionParameterisation

new_pred_param = XYPhiPredictionParameterisation(experiments,
  [det_param], [s0_param], [xl1o_param, xl2o_param], [xl1uc_param, xl2uc_param])

print "NEW CLASSES"

# make a new target object
from dials.algorithms.refinement.target_new import LeastSquaresPositionalResidualWithRmsdCutoff

new_target = LeastSquaresPositionalResidualWithRmsdCutoff(experiments, ref_predictor, refman,
               prediction_parameterisation=new_pred_param)

#see if we can use the target to predict
new_target.predict()

# can we now finalise the reflection manager?
refman.finalise()

print "number of matches from new relfeciotn manager", len(refman.get_matches())

# see if we can calculate gradients
dX_dp, dY_dp, dPhi_dp = new_target.calculate_gradients()

# assign a sort index to the reflection table
new_matches = refman.get_matches()
from dials.array_family import flex
new_matches['order'] = flex.size_t_range(len(new_matches))
new_matches['dX_dp0'] = dX_dp[0]
new_matches['dY_dp0'] = dY_dp[0]
new_matches['dPhi_dp0'] = dPhi_dp[0]

print "OLD CLASSES"

# Are the value what we expect? Test versus the old classes
old_ref_predictor = ScansRayPredictor(experiments, sweep_range)

from dials.algorithms.refinement.target import \
      LeastSquaresPositionalResidualWithRmsdCutoff as OldTarget
from dials.algorithms.refinement.target import \
      ReflectionManager as OldReflectionManager
from dials.algorithms.refinement.parameterisation.prediction_parameters import \
    XYPhiPredictionParameterisation as OldXYPhiPredictionParameterisation
old_pred_param = OldXYPhiPredictionParameterisation(experiments,
  [det_param], [s0_param], [xl1o_param, xl2o_param], [xl1uc_param, xl2uc_param])
print "BUILDING OLD STYLE REFLECTION MANAGER"
old_refman = OldReflectionManager(old_reflections, experiments,
                               verbosity=2, iqr_multiplier=None)
old_target = OldTarget(experiments,
    old_ref_predictor, old_refman, old_pred_param)
print "OLD STYLE PREDICTION AND GRAD CALC"
old_target.predict()


old_matches = old_refman.get_matches()
print "number of matches from old relfeciotn manager", len(old_matches)

# Now we want to compare the gradients in new_matches with those in old_matches.
# are they the same?
new_matches.sort('x_resid')
# sort each element of the gradients
for i in range(len(dX_dp)):
  dX_dp[i] = dX_dp[i].select(new_matches['order'])
  dY_dp[i] = dY_dp[i].select(new_matches['order'])
  dPhi_dp[i] = dPhi_dp[i].select(new_matches['order'])
old_matches = sorted(old_matches, key=lambda e: e.x_resid)

for i in range(10):
  print new_matches[i]['miller_index'], dX_dp[0][i], dY_dp[0][i], dPhi_dp[0][i], old_matches[i].miller_index, old_matches[i].gradients[0]

#from dials.util.command_line import interactive_console; interactive_console()

# test all gradients
print "TESTING GRADIENTS"
for i in range(len(new_matches)):
#for i in range(1):
  for j in range(len(dX_dp)):
    #print "param", j
    assert approx_equal(dX_dp[j][i], old_matches[i].gradients[j][0])
    assert approx_equal(dY_dp[j][i], old_matches[i].gradients[j][1])
    assert approx_equal(dPhi_dp[j][i], old_matches[i].gradients[j][2])


print "OK"
from dials.util.command_line import interactive_console; interactive_console()

#for i in range(2):
#  pp.pprint(refman.get_obs()[i])

