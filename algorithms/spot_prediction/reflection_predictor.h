
#ifndef DIALS_ALGORITHMS_SPOT_PREDICTION_REFLECTION_PREDICTOR_H
#define DIALS_ALGORITHMS_SPOT_PREDICTION_REFLECTION_PREDICTOR_H

#include <dxtbx/model/beam.h>
#include <dxtbx/model/detector.h>
#include <dxtbx/model/goniometer.h>
#include <dxtbx/model/scan.h>
#include <dials/array_family/reflection_table.h>
#include <dials/algorithms/spot_prediction/index_generator.h>
#include <dials/algorithms/spot_prediction/ray_predictor.h>
#include <dials/algorithms/spot_prediction/stills_ray_predictor.h>
#include <dials/algorithms/spot_prediction/ray_intersection.h>

namespace dials { namespace algorithms {

  using boost::shared_ptr;
  using dxtbx::model::Beam;
  using dxtbx::model::Detector;
  using dxtbx::model::Goniometer;
  using dxtbx::model::Scan;

  class ScanStaticReflectionPredictor {

    typedef cctbx::miller::index<> miller_index;

    struct prediction_data {

      af::shared< miller_index > hkl;
      af::shared< std::size_t > panel;
      af::shared< bool > enter;
      af::shared< vec3<double> > s1;
      af::shared< vec3<double> > xyz_px;
      af::shared< vec3<double> > xyz_mm;

      prediction_data(af::reflection_table &table) {
        hkl    = table.get< miller_index >("miller_index");
        panel  = table.get< std::size_t >("panel");
        enter  = table.get< bool >("entering");
        s1     = table.get< vec3<double> >("s1");
        xyz_px = table.get< vec3<double> >("xyzcal.px");
        xyz_mm = table.get< vec3<double> >("xyzcal.mm");
      }
    };

  public:

    ScanStaticReflectionPredictor(
        shared_ptr<Beam> beam,
        shared_ptr<Detector> detector,
        shared_ptr<Goniometer> goniometer,
        shared_ptr<Scan> scan)
      : beam_(beam),
        detector_(detector),
        goniometer_(goniometer),
        scan_(scan) {}

    af::reflection_table all_observable() const {
      af::reflection_table table;
      prediction_data predictions(table);
      RayPredictor2 predict_rays = init_ray_predictor();
      IndexGenerator indices(unit_cell_, space_group_type_, dmin_);
      for (;;) {
        miller_index h = indices.next();
        if (h.is_zero()) {
          break;
        }
        append_for_index(predict_rays, predictions, h);
      }
      return table;
    }

    af::reflection_table observed(
        const af::const_ref< miller_index > &h) const {
      af::reflection_table table;
      prediction_data predictions(table);
      RayPredictor2 predict_rays = init_ray_predictor();
      for (std::size_t i = 0; i < h.size(); ++i) {
        append_for_index(predict_rays, predictions, h[i]);
      }
      return table;
    }

  private:

    RayPredictor2 init_ray_predictor() const {
      return RayPredictor2(
          beam_->get_s0(),
          goniometer_->get_rotation_axis(),
          scan_->get_oscillation_range());
    }

    void append_for_index(const RayPredictor2 &predict_rays,
        prediction_data &p, const miller_index &h) const {
      af::small<Ray, 2> rays = predict_rays(h, ub_);
      for (std::size_t i = 0; i < rays.size(); ++i) {
        append_for_ray(p, h, rays[i]);
      }
    }

    void append_for_ray(prediction_data &p, const miller_index &h, const Ray &ray) const {
      try {

        // Get the impact on the detector
        Detector::coord_type impact = (*detector_).get_ray_intersection(ray.s1);
        std::size_t panel = impact.first;
        vec2<double> mm = impact.second;
        vec2<double> px = (*detector_)[panel].millimeter_to_pixel(mm);

        // Get the frames that a reflection with this angle will be observed at
        af::shared<double> frames = (*scan_).get_array_indices_with_angle(ray.angle);
        for (std::size_t i = 0; i < frames.size(); ++i) {
          p.hkl.push_back(h);
          p.enter.push_back(ray.entering);
          p.s1.push_back(ray.s1);
          p.xyz_mm.push_back(vec3<double>(mm[0], mm[1], ray.angle));
          p.xyz_px.push_back(vec3<double>(px[0], px[1], frames[i]));
          p.panel.push_back(panel);
        }

      } catch(dxtbx::error) {
        // do nothing
      }
    }

    cctbx::uctbx::unit_cell unit_cell_;
    cctbx::sgtbx::space_group_type space_group_type_;
    mat3<double> ub_;
    double dmin_;
    shared_ptr<Beam> beam_;
    shared_ptr<Detector> detector_;
    shared_ptr<Goniometer> goniometer_;
    shared_ptr<Scan> scan_;
  };


  class StillsReflectionPredictor {

    typedef cctbx::miller::index<> miller_index;

    struct prediction_data {

      af::shared< miller_index > hkl;
      af::shared< std::size_t > panel;
      af::shared< bool > enter;
      af::shared< vec3<double> > s1;
      af::shared< vec3<double> > xyz_px;
      af::shared< vec3<double> > xyz_mm;

      prediction_data(af::reflection_table &table) {
        hkl    = table.get< miller_index >("miller_index");
        panel  = table.get< std::size_t >("panel");
        enter  = table.get< bool >("entering");
        s1     = table.get< vec3<double> >("s1");
        xyz_px = table.get< vec3<double> >("xyzcal.px");
        xyz_mm = table.get< vec3<double> >("xyzcal.mm");
      }
    };

  public:

    StillsReflectionPredictor(
        shared_ptr<Beam> beam,
        shared_ptr<Detector> detector,
        mat3<double> ub)
      : beam_(beam),
        detector_(detector),
        ub_(ub) { }

    af::reflection_table all_observable() const {
      DIALS_ERROR("Not implemented");
      return af::reflection_table();
    }

    af::reflection_table observed(
        const af::const_ref< miller_index > &h,
        const af::const_ref< std::size_t > id) const {
      af::reflection_table table;
      prediction_data predictions(table);
      StillsRayPredictor predict_rays = init_ray_predictor();
      for (std::size_t i = 0; i < h.size(); ++i) {
        append_for_index(predict_rays, predictions, h[i]);
      }
      return table;
    }

  private:

    StillsRayPredictor init_ray_predictor() const {
      return StillsRayPredictor(beam_->get_s0());
    }

    void append_for_index(const StillsRayPredictor &predict_rays,
        prediction_data &p, const miller_index &h) const {
      af::small<Ray, 2> rays = predict_rays(h, ub_);
      for (std::size_t i = 0; i < rays.size(); ++i) {
        append_for_ray(p, h, rays[i]);
      }
    }

    void append_for_ray(prediction_data &p, const miller_index &h, const Ray &ray) const {
      try {

        // Get the impact on the detector
        Detector::coord_type impact = (*detector_).get_ray_intersection(ray.s1);
        std::size_t panel = impact.first;
        vec2<double> mm = impact.second;
        vec2<double> px = (*detector_)[panel].millimeter_to_pixel(mm);

        // Add the reflections to the table
        p.hkl.push_back(h);
        p.enter.push_back(ray.entering);
        p.s1.push_back(ray.s1);
        p.xyz_mm.push_back(vec3<double>(mm[0], mm[1], 0.0));
        p.xyz_px.push_back(vec3<double>(px[0], px[1], 0.0));
        p.panel.push_back(panel);

      } catch(dxtbx::error) {
        // do nothing
      }
    }

    shared_ptr<Beam> beam_;
    shared_ptr<Detector> detector_;
    mat3<double> ub_;
  };
}} // namespace dials::algorithms

#endif // DIALS_ALGORITHMS_SPOT_PREDICTION_REFLECTION_PREDICTOR_H
