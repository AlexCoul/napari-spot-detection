"""
This module is an example of a barebones QWidget plugin for napari

It implements the Widget specification.
see: https://napari.org/plugins/stable/guides.html#widgets

Replace code below according to your needs.
"""

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QWidget, 
    QHBoxLayout, 
    QVBoxLayout, 
    QGridLayout, 
    QGroupBox, 
    QPushButton, 
    QSlider, 
    QLabel, 
    QLineEdit, 
    QCheckBox, 
    QComboBox,
    QFileDialog, 
    QScrollArea, 
    QSizePolicy,
)
from superqt import QLabeledDoubleRangeSlider, QLabeledDoubleSlider
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import tifffile
from localize_psf import fit_psf, camera
import itertools
import json
import warnings
import napari
from pathlib import Path
import sys

if '/home/alexis/Postdoc_ASU/Projects/opm-merfish-analysis/src/' not in sys.path:
    sys.path.append('/home/alexis/Postdoc_ASU/Projects/opm-merfish-analysis/src/')
from SPOTS3D import SPOTS3D
from _imageprocessing import deskew



class FullSlider(QWidget):
    """
    Custom Slider widget with its label and value displayed.
    """

    def __init__(self, range=(0, 1), step=0.01, label='', layout=QHBoxLayout, *args, **kwargs):
        super(FullSlider, self).__init__(*args, **kwargs)

        self.step = step

        layout = layout()

        self.label = QLabel(label)
        layout.addWidget(self.label)

        if isinstance(layout, QHBoxLayout):
            self.sld = QSlider(Qt.Horizontal)
        else:
            self.sld = QSlider(Qt.Vertical)
        # wrangle range and steps as QtSlider handles only integers
        mini = int(range[0] / step)
        maxi = int(range[1] / step)
        # self.sld.setRange(*range)
        self.sld.setRange(mini, maxi)
        self.sld.setPageStep(1)  # minimum possible
        self.sld.valueChanged.connect(self._convert_value)
        # the real converted value we want
        self.value = self.sld.value() * self.step
        layout.addWidget(self.sld)

        self.readout = QLabel(str(self.value))
        layout.addWidget(self.readout)

        self.setLayout(layout)
        # make available the connect method
        self.valueChanged = self.sld.valueChanged

    def _convert_value(self):
        self.value = self.sld.value() * self.step
        self.readout.setText("{:.2f}".format(self.value))

    def setValue(self, value):
        # first set the slider at the correct position
        self.sld.setValue(int(value / self.step))
        # then convert the slider position to have the value
        # we don't directly convert in order to account for rounding errors in the silder
        self._convert_value()


class SpotDetection(QWidget):
    def __init__(self, napari_viewer):
        super().__init__()
        self.viewer = napari_viewer
        # automatic adaptation of parameters when steps complete, False when loading parameters
        self.auto_params = True 
        self.spots3d = None
        
        self.setLayout(QVBoxLayout())
        self.layout().setSpacing(0)
        self.layout().setContentsMargins(10, 10, 10, 10)

        # general scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spot_wdg = self._create_gui()
        self._scroll.setWidget(self.spot_wdg)
        self.layout().addWidget(self._scroll)

        
    def _create_gui(self):
        wdg = QWidget()
        wdg_layout = QVBoxLayout()
        wdg_layout.setSpacing(20)
        wdg_layout.setContentsMargins(10, 10, 10, 10)
        wdg.setLayout(wdg_layout)
        
        self.spot_size_groupBox = self._create_spot_size_groupBox()
        wdg_layout.addWidget(self.spot_size_groupBox)
        
        self.deconv_groupBox = self._create_deconv_groupBox()
        wdg_layout.addWidget(self.deconv_groupBox)
        
        # self.adapthist_groupBox = self._create_adapthist_groupBox()
        # wdg_layout.addWidget(self.adapthist_groupBox)
        
        self.localmax_groupBox = self._create_localmax_groupBox()
        wdg_layout.addWidget(self.localmax_groupBox)
        
        self.gaussianfit_groupBox = self._create_gaussianfit_groupBox()
        wdg_layout.addWidget(self.gaussianfit_groupBox)
        
        self.filter_groupBox = self._create_filter_groupBox()
        wdg_layout.addWidget(self.filter_groupBox)
        
        self.save_groupBox = self._create_save_groupBox()
        wdg_layout.addWidget(self.save_groupBox)

        return wdg
    

    def _create_spot_size_groupBox(self):
        group = QGroupBox(title="Physical parameters")
        group.setCheckable(False)
        # group.setChecked(True)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum))
        group_layout = QVBoxLayout()
        group.setLayout(group_layout)

        # expected spot size
        self.lab_na = QLabel('NA')
        self.txt_na = QLineEdit()
        self.txt_na.setText('1.35')
        self.lab_ri = QLabel('RI')
        self.txt_ri = QLineEdit()
        self.txt_ri.setText('1.4')
        self.lab_lambda_em = QLabel('emission wavelenth (nm)')
        self.txt_lambda_em = QLineEdit()
        self.txt_lambda_em.setText('670')
        self.lab_dc = QLabel('pixel size (µm)')
        self.txt_dc = QLineEdit()
        self.txt_dc.setText('0.115')
        self.lab_dstage = QLabel('frames spacing (µm)')
        self.txt_dstage = QLineEdit()
        self.txt_dstage.setText('0.400')
        self.lab_skewed = QLabel('skewed data')
        self.chk_skewed = QCheckBox()
        self.chk_skewed.setChecked(True)
        self.lab_angle = QLabel('angle (°)')
        self.txt_angle = QLineEdit()
        self.txt_angle.setText('30')
        self.lab_spot_size_xy_um = QLabel('Expected spot size xy (µm)')
        self.txt_spot_size_xy_um = QLineEdit()
        self.txt_spot_size_xy_um.setText('')
        self.lab_spot_size_z_um = QLabel('Expected spot size z (µm)')
        self.txt_spot_size_z_um = QLineEdit()
        self.txt_spot_size_z_um.setText('')
        # in the future, allow user to define spot parameters from pixel size
        # self.lab_spot_size_xy = QLabel('Expected spot size xy (px)')
        # self.txt_spot_size_xy = QLineEdit()
        # self.txt_spot_size_xy.setText('')
        # self.lab_spot_size_z = QLabel('Expected spot size z (px)')
        # self.txt_spot_size_z = QLineEdit()
        # self.txt_spot_size_z.setText('')
        self.but_make_psf = QPushButton()
        self.but_make_psf.setText('make PSF')
        self.but_make_psf.clicked.connect(self._make_psf)
        self.but_load_psf = QPushButton()
        self.but_load_psf.setText('load PSF')
        self.but_load_psf.clicked.connect(self._load_psf)
        self.but_load_model = QPushButton()
        self.but_load_model.setText('Load model')
        self.but_load_model.clicked.connect(self._get_spot3d)

        # layout for spot size parametrization
        spotsizeLayout_optics = QHBoxLayout()
        spotsizeLayout_optics.addWidget(self.lab_na)
        spotsizeLayout_optics.addWidget(self.txt_na)
        spotsizeLayout_optics.addWidget(self.lab_ri)
        spotsizeLayout_optics.addWidget(self.txt_ri)
        spotsizeLayout_optics.addWidget(self.lab_lambda_em)
        spotsizeLayout_optics.addWidget(self.txt_lambda_em)
        spotsizeLayout_spacing = QHBoxLayout()
        spotsizeLayout_spacing.addWidget(self.lab_dc)
        spotsizeLayout_spacing.addWidget(self.txt_dc)
        spotsizeLayout_spacing.addWidget(self.lab_dstage)
        spotsizeLayout_spacing.addWidget(self.txt_dstage)
        spotsizeLayout_skewed = QHBoxLayout()
        spotsizeLayout_skewed.addWidget(self.lab_skewed)
        spotsizeLayout_skewed.addWidget(self.chk_skewed)
        spotsizeLayout_skewed.addWidget(self.lab_angle)
        spotsizeLayout_skewed.addWidget(self.txt_angle)
        spotsizeLayout_zxy_um = QHBoxLayout()
        spotsizeLayout_zxy_um.addWidget(self.lab_spot_size_xy_um)
        spotsizeLayout_zxy_um.addWidget(self.txt_spot_size_xy_um)
        spotsizeLayout_zxy_um.addWidget(self.lab_spot_size_z_um)
        spotsizeLayout_zxy_um.addWidget(self.txt_spot_size_z_um)
        # spotsizeLayout_zxy = QHBoxLayout()  # not used yet
        # spotsizeLayout_zxy.addWidget(self.lab_spot_size_xy)
        # spotsizeLayout_zxy.addWidget(self.txt_spot_size_xy)
        # spotsizeLayout_zxy.addWidget(self.lab_spot_size_z)
        # spotsizeLayout_zxy.addWidget(self.txt_spot_size_z)
        spotsizeLayout_psf = QHBoxLayout()
        spotsizeLayout_psf.addWidget(self.but_make_psf)
        spotsizeLayout_psf.addWidget(self.but_load_psf)
        group_layout.addLayout(spotsizeLayout_optics)
        group_layout.addLayout(spotsizeLayout_spacing)
        group_layout.addLayout(spotsizeLayout_skewed)
        # group_layout.addLayout(spotsizeLayout_zxy_um)
        # spotsizeLayout.addLayout(spotsizeLayout_zxy)
        group_layout.addLayout(spotsizeLayout_psf)
        group_layout.addWidget(self.but_load_model)

        return group
    
    def _create_deconv_groupBox(self):
        group = QGroupBox(title="Deconvolve")
        group.setCheckable(True)
        group.setChecked(True)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum))
        group_layout = QVBoxLayout()
        group.setLayout(group_layout)

        # Deconvolution parameters
        self.lab_deconv_iter = QLabel('iterations')
        self.txt_deconv_iter = QLineEdit()
        self.txt_deconv_iter.setText('30')
        self.lab_deconv_tvtau = QLabel('TV tau')
        self.txt_deconv_tvtau = QLineEdit()
        self.txt_deconv_tvtau.setText('.0001')
        self.but_run_deconvolution = QPushButton()
        self.but_run_deconvolution.setText('Run deconvolution')
        self.but_run_deconvolution.clicked.connect(self._run_deconvolution)

        # layout for deconvolution
        deconvLayout = QHBoxLayout()
        deconvLayout.addWidget(self.lab_deconv_iter)
        deconvLayout.addWidget(self.txt_deconv_iter)
        deconvLayout.addWidget(self.lab_deconv_tvtau)
        deconvLayout.addWidget(self.txt_deconv_tvtau)
        group_layout.addLayout(deconvLayout)
        group_layout.addWidget(self.but_run_deconvolution)

        return group


    def _create_adapthist_groupBox(self):
        group = QGroupBox(title="Adaptive histogram")
        group.setCheckable(True)
        group.setChecked(False)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum))
        group_layout = QVBoxLayout()
        group.setLayout(group_layout)

        # Adaptive histogram
        self.lab_adapthist_x = QLabel('x')
        self.txt_adapthist_x = QLineEdit()
        self.txt_adapthist_x.setText('25')
        self.lab_adapthist_y = QLabel('y')
        self.txt_adapthist_y = QLineEdit()
        self.txt_adapthist_y.setText('25')
        self.lab_adapthist_z = QLabel('z')
        self.txt_adapthist_z = QLineEdit()
        self.txt_adapthist_z.setText('25')
        self.but_run_adapthist = QPushButton()
        self.but_run_adapthist.setText('Run adaptive histogram')
        self.but_run_adapthist.clicked.connect(self._run_adaptive_histogram)

        # layout for adaptive histogram
        adapthistLayout = QHBoxLayout()
        # adapthistLayout.addWidget(self.lab_adapthist)
        # adapthistLayout.addWidget(self.chk_adapthist)
        adapthistLayout.addWidget(self.lab_adapthist_x)
        adapthistLayout.addWidget(self.txt_adapthist_x)
        adapthistLayout.addWidget(self.lab_adapthist_y)
        adapthistLayout.addWidget(self.txt_adapthist_y)
        adapthistLayout.addWidget(self.lab_adapthist_z)
        adapthistLayout.addWidget(self.txt_adapthist_z)
        group_layout.addLayout(adapthistLayout)
        group_layout.addWidget(self.but_run_adapthist)

        return group


    def _create_localmax_groupBox(self):
        group = QGroupBox(title="Find local maxima")
        group.setCheckable(False)
        # group.setChecked(True)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum))
        group_layout = QVBoxLayout()
        group.setLayout(group_layout)

        # Differential of Gaussian parameters 
        self.lab_sigma_ratio = QLabel('DoG sigma ratio big / small')
        self.txt_sigma_ratio = QLineEdit()
        self.txt_sigma_ratio.setText('1.6')
        self.but_auto_sigmas = QPushButton()
        self.but_auto_sigmas.setText('Auto sigmas')
        self.but_auto_sigmas.clicked.connect(self._make_sigmas_factors)
        # DoG blob detection widgets
        self.lab_dog_sigma_x_factor = QLabel('sigma DoG x factor')
        self.sld_dog_sigma_x_factor = QLabeledDoubleRangeSlider(Qt.Orientation.Horizontal)
        self.sld_dog_sigma_x_factor.setRange(0, 8)
        self.sld_dog_sigma_x_factor.setValue([0.5, 5])
        self.lab_dog_sigma_y_factor = QLabel('sigma DoG y factor')
        self.sld_dog_sigma_y_factor = QLabeledDoubleRangeSlider(Qt.Orientation.Horizontal)
        self.sld_dog_sigma_y_factor.setRange(0, 8)
        self.sld_dog_sigma_y_factor.setValue([0.5, 5])
        self.lab_dog_sigma_z_factor = QLabel('sigma DoG z factor')
        self.sld_dog_sigma_z_factor = QLabeledDoubleRangeSlider(Qt.Orientation.Horizontal)
        self.sld_dog_sigma_z_factor.setRange(0, 8)
        self.sld_dog_sigma_z_factor.setValue([0.5, 5])
        # self.sld_dog_thresh = FullSlider(range=(0.1, 20), step=0.1, label="Blob threshold")
        self.lab_dog_thresh = QLabel('DoG threshold')
        self.sld_dog_thresh = QLabeledDoubleSlider(Qt.Orientation.Horizontal)
        self.sld_dog_thresh.setRange(0, 500)
        self.sld_dog_thresh.setValue(50)
        # self.sld_dog_thresh.setBarIsRigid(False) not implemented for QLabeledDoubleSlider :'(
        self.lab_dog_choice = QLabel('run DoG on:')
        self.cbx_dog_choice = QComboBox()
        self.cbx_dog_choice.addItems(['deconvolved', 'raw'])

        self.but_dog = QPushButton()
        self.but_dog.setText('Apply DoG')
        self.but_dog.clicked.connect(self._compute_dog)

        # Merge local maxima
        self.lab_merge_peaks= QLabel('Merge peaks')
        self.chk_merge_peaks = QCheckBox()
        self.chk_merge_peaks.setChecked(False)
        self.lab_min_spot_xy_factor = QLabel('min spot xy factor')
        self.sld_min_spot_xy_factor = QLabeledDoubleSlider(Qt.Orientation.Horizontal)
        self.sld_min_spot_xy_factor.setRange(0, 10)
        self.sld_min_spot_xy_factor.setValue(2.5)
        self.lab_min_spot_z_factor = QLabel('min spot z factor')
        self.sld_min_spot_z_factor = QLabeledDoubleSlider(Qt.Orientation.Horizontal)
        self.sld_min_spot_z_factor.setRange(0, 10)
        self.sld_min_spot_z_factor.setValue(2.5)
        self.but_find_peaks = QPushButton()
        self.but_find_peaks.setText('Find peaks')
        self.but_find_peaks.clicked.connect(self._find_peaks)

        self.but_merge_peaks = QPushButton()
        self.but_merge_peaks.setText('Merge peaks')
        self.but_merge_peaks.clicked.connect(self._merge_peaks)

        # layout for DoG filtering
        dogLayout_sigmas = QHBoxLayout()
        dogLayout_sigmas.addWidget(self.but_auto_sigmas)
        dogLayout_sigmas.addWidget(self.lab_sigma_ratio)
        dogLayout_sigmas.addWidget(self.txt_sigma_ratio)
        group_layout.addLayout(dogLayout_sigmas)
        dogLayout_sigmas_x_factors = QHBoxLayout()
        dogLayout_sigmas_x_factors.addWidget(self.lab_dog_sigma_x_factor)
        dogLayout_sigmas_x_factors.addWidget(self.sld_dog_sigma_x_factor)
        dogLayout_sigmas_y_factors = QHBoxLayout()
        dogLayout_sigmas_y_factors.addWidget(self.lab_dog_sigma_y_factor)
        dogLayout_sigmas_y_factors.addWidget(self.sld_dog_sigma_y_factor)
        dogLayout_sigmas_z_factors = QHBoxLayout()
        dogLayout_sigmas_z_factors.addWidget(self.lab_dog_sigma_z_factor)
        dogLayout_sigmas_z_factors.addWidget(self.sld_dog_sigma_z_factor)
        group_layout.addLayout(dogLayout_sigmas_x_factors)
        group_layout.addLayout(dogLayout_sigmas_y_factors)
        group_layout.addLayout(dogLayout_sigmas_z_factors)
        dogLayout_dog_choice = QHBoxLayout()
        dogLayout_dog_choice.addWidget(self.lab_dog_choice)
        dogLayout_dog_choice.addWidget(self.cbx_dog_choice)
        group_layout.addLayout(dogLayout_dog_choice)
        group_layout.addWidget(self.but_dog)
        dogThreshLayout = QHBoxLayout()
        dogThreshLayout.addWidget(self.lab_dog_thresh)
        dogThreshLayout.addWidget(self.sld_dog_thresh)
        group_layout.addLayout(dogThreshLayout)
        group_layout.addWidget(self.but_find_peaks)
        mergePeaksLayout = QHBoxLayout()
        mergePeaksLayout.addWidget(self.lab_merge_peaks)
        mergePeaksLayout.addWidget(self.chk_merge_peaks)
        mergePeaksXYfactorLayout = QHBoxLayout()
        mergePeaksXYfactorLayout.addWidget(self.lab_min_spot_xy_factor)
        mergePeaksXYfactorLayout.addWidget(self.sld_min_spot_xy_factor)
        mergePeaksZfactorLayout = QHBoxLayout()
        mergePeaksZfactorLayout.addWidget(self.lab_min_spot_z_factor)
        mergePeaksZfactorLayout.addWidget(self.sld_min_spot_z_factor)
        group_layout.addLayout(mergePeaksLayout)
        group_layout.addLayout(mergePeaksXYfactorLayout)
        group_layout.addLayout(mergePeaksZfactorLayout)
        group_layout.addWidget(self.but_merge_peaks)

        return group


    def _create_gaussianfit_groupBox(self):
        group = QGroupBox(title="Gaussian fit")
        group.setCheckable(False)
        # group.setChecked(True)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum))
        group_layout = QVBoxLayout()
        group.setLayout(group_layout)

        # gaussian fitting widgets
        self.lab_n_spots_to_fit= QLabel('n spots to fit')
        self.txt_n_spots_to_fit= QLineEdit()
        self.txt_n_spots_to_fit.setText('250000')
        self.lab_roi_sizes = QLabel('Fit ROI size factors (z / y / x)')
        self.txt_roi_z_factor= QLineEdit()
        self.txt_roi_z_factor.setText('3')
        self.txt_roi_y_factor = QLineEdit()
        self.txt_roi_y_factor.setText('3')
        self.txt_roi_x_factor = QLineEdit()
        self.txt_roi_x_factor.setText('3')

        self.but_fit = QPushButton()
        self.but_fit.setText('Fit spots')
        self.but_fit.clicked.connect(self._fit_spots)

        self.lab_filter_percentile = QLabel('Percentiles auto params (min / max)')
        self.txt_filter_percentile_min = QLineEdit()
        self.txt_filter_percentile_min.setText('0')
        self.txt_filter_percentile_max = QLineEdit()
        self.txt_filter_percentile_max.setText('100')

        self.but_plot_fitted = QPushButton()
        self.but_plot_fitted.setText('Plot fitted parameters')
        self.but_plot_fitted.clicked.connect(self._plot_fitted_params)
        self.but_plot_fitted_2D = QPushButton()
        self.but_plot_fitted_2D.setText('Plot 2D distributions')
        self.but_plot_fitted_2D.clicked.connect(self._plot_fitted_params_2D)

        # layout for fitting gaussian spots
        nspotsLayout = QHBoxLayout()
        nspotsLayout.addWidget(self.lab_n_spots_to_fit)
        nspotsLayout.addWidget(self.txt_n_spots_to_fit)
        group_layout.addLayout(nspotsLayout)
        roisizesLayout = QHBoxLayout()
        roisizesLayout.addWidget(self.lab_roi_sizes)
        roisizesLayout.addWidget(self.txt_roi_z_factor)
        roisizesLayout.addWidget(self.txt_roi_y_factor)
        roisizesLayout.addWidget(self.txt_roi_x_factor)
        group_layout.addLayout(roisizesLayout)
        group_layout.addWidget(self.but_fit)
        plotFittedLayout = QHBoxLayout()
        plotFittedLayout.addWidget(self.but_plot_fitted)
        plotFittedLayout.addWidget(self.but_plot_fitted_2D)
        group_layout.addLayout(plotFittedLayout)
        percentileLayout = QHBoxLayout()
        percentileLayout.addWidget(self.lab_filter_percentile)
        percentileLayout.addWidget(self.txt_filter_percentile_min)
        percentileLayout.addWidget(self.txt_filter_percentile_max)
        group_layout.addLayout(percentileLayout)

        return group


    def _create_filter_groupBox(self):
        group = QGroupBox(title="Spot filtering")
        group.setCheckable(False)
        # group.setChecked(True)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum))
        group_layout = QVBoxLayout()
        group.setLayout(group_layout)

        # spot filtering widgets
        self.lab_filter_amplitude_range = QLabel('Range amplitude')
        self.sld_filter_amplitude_range = QLabeledDoubleRangeSlider(Qt.Orientation.Horizontal)
        self.sld_filter_amplitude_range.setRange(1, 4)
        self.sld_filter_amplitude_range.setValue([2, 3])
        self.sld_filter_amplitude_range.setBarIsRigid(False)
        self.chk_filter_amplitude_min = QCheckBox()
        self.chk_filter_amplitude_max = QCheckBox()
        self.lab_filter_sigma_xy_range = QLabel('Range sigma x/y')
        self.sld_filter_sigma_xy_factor = QLabeledDoubleRangeSlider(Qt.Orientation.Horizontal)
        self.sld_filter_sigma_xy_factor.setRange(0, 20)
        self.sld_filter_sigma_xy_factor.setValue([0.25, 8])
        self.sld_filter_sigma_xy_factor.setBarIsRigid(False)
        self.chk_filter_sigma_xy_min = QCheckBox()
        self.chk_filter_sigma_xy_max = QCheckBox()
        self.lab_filter_sigma_z_range = QLabel('Range sigma z')
        self.sld_filter_sigma_z_factor = QLabeledDoubleRangeSlider(Qt.Orientation.Horizontal)
        self.sld_filter_sigma_z_factor.setRange(0, 20)
        self.sld_filter_sigma_z_factor.setValue([0.2, 6])
        self.sld_filter_sigma_z_factor.setBarIsRigid(False)
        self.chk_filter_sigma_z_min = QCheckBox()
        self.chk_filter_sigma_z_max = QCheckBox()
        self.lab_filter_sigma_ratio_range = QLabel('Range sigma ratio z/xy')
        self.sld_filter_sigma_ratio_range = QLabeledDoubleRangeSlider(Qt.Orientation.Horizontal)
        self.sld_filter_sigma_ratio_range.setRange(0, 10)
        self.sld_filter_sigma_ratio_range.setValue([1.25, 6])
        self.sld_filter_sigma_ratio_range.setBarIsRigid(False)
        self.chk_filter_sigma_ratio_min = QCheckBox()
        self.chk_filter_sigma_ratio_max = QCheckBox()
        self.lab_fit_dist_max_err_z_factor = QLabel('fit_dist_max_err_z_factor')
        self.sld_fit_dist_max_err_z_factor = QLabeledDoubleSlider(Qt.Orientation.Horizontal)
        self.sld_fit_dist_max_err_z_factor.setRange(0, 20)
        self.sld_fit_dist_max_err_z_factor.setValue(5)
        self.chk_fit_dist_max_err_z_factor = QCheckBox()
        self.lab_fit_dist_max_err_xy_factor = QLabel('fit_dist_max_err_xy_factor')
        self.sld_fit_dist_max_err_xy_factor = QLabeledDoubleSlider(Qt.Orientation.Horizontal)
        self.sld_fit_dist_max_err_xy_factor.setRange(0, 20)
        self.sld_fit_dist_max_err_xy_factor.setValue(7)
        self.chk_fit_dist_max_err_xy_factor = QCheckBox()
        self.lab_min_spot_sep_z_factor = QLabel('min_spot_sep_z_factor')
        self.sld_min_spot_sep_z_factor = QLabeledDoubleSlider(Qt.Orientation.Horizontal)
        self.sld_min_spot_sep_z_factor.setRange(0, 5)
        self.sld_min_spot_sep_z_factor.setValue(2)
        self.chk_min_spot_sep_z_factor = QCheckBox()
        self.lab_min_spot_sep_xy_factor = QLabel('min_spot_sep_xy_factor')
        self.sld_min_spot_sep_xy_factor = QLabeledDoubleSlider(Qt.Orientation.Horizontal)
        self.sld_min_spot_sep_xy_factor.setRange(0, 5)
        self.sld_min_spot_sep_xy_factor.setValue(1)
        self.chk_min_spot_sep_xy_factor = QCheckBox()
        self.lab_dist_boundary_z_factor = QLabel('dist_boundary_z_factor')
        self.sld_dist_boundary_z_factor = QLabeledDoubleSlider(Qt.Orientation.Horizontal)
        self.sld_dist_boundary_z_factor.setRange(0, 0.5)
        self.sld_dist_boundary_z_factor.setValue(0.05)
        self.chk_dist_boundary_z_factor = QCheckBox()
        self.lab_dist_boundary_xy_factor = QLabel('dist_boundary_xy_factor')
        self.sld_dist_boundary_xy_factor = QLabeledDoubleSlider(Qt.Orientation.Horizontal)
        self.sld_dist_boundary_xy_factor.setRange(0, 0.5)
        self.sld_dist_boundary_xy_factor.setValue(0.05)
        self.chk_dist_boundary_xy_factor= QCheckBox()
        self.lab_filter_chi_squared = QLabel('min chi squared')
        self.sld_filter_chi_squared = QLabeledDoubleSlider(Qt.Orientation.Horizontal)
        self.sld_filter_chi_squared.setRange(1, 3)
        self.sld_filter_chi_squared.setValue(2)
        self.chk_filter_chi_squared = QCheckBox()
        self.but_filter = QPushButton()
        self.but_filter.setText('Filter spots')
        self.but_filter.clicked.connect(self._filter_spots)
        self.but_inspect= QPushButton()
        self.but_inspect.setText('Inspect filtering')
        self.but_inspect.clicked.connect(self._inspect_filtering)

        # layout for filtering gaussian spots
        filterLayout = QGridLayout()
        # amplitudes
        filterLayout.addWidget(self.lab_filter_amplitude_range, 0, 0)
        filterLayout.addWidget(self.sld_filter_amplitude_range, 0, 1)
        chk_layout = QHBoxLayout()
        chk_layout.addWidget(self.chk_filter_amplitude_min)
        chk_layout.addWidget(self.chk_filter_amplitude_max)
        filterLayout.addLayout(chk_layout, 0, 2)
        # sigma xy
        filterLayout.addWidget(self.lab_filter_sigma_xy_range, 1, 0)
        filterLayout.addWidget(self.sld_filter_sigma_xy_factor, 1, 1)
        chk_layout = QHBoxLayout()
        chk_layout.addWidget(self.chk_filter_sigma_xy_min)
        chk_layout.addWidget(self.chk_filter_sigma_xy_max)
        filterLayout.addLayout(chk_layout, 1, 2)
        # sigma z
        filterLayout.addWidget(self.lab_filter_sigma_z_range, 2, 0)
        filterLayout.addWidget(self.sld_filter_sigma_z_factor, 2, 1)
        chk_layout = QHBoxLayout()
        chk_layout.addWidget(self.chk_filter_sigma_z_min)
        chk_layout.addWidget(self.chk_filter_sigma_z_max)
        filterLayout.addLayout(chk_layout, 2, 2)
        # sigma ratio z/xy
        filterLayout.addWidget(self.lab_filter_sigma_ratio_range, 3, 0)
        filterLayout.addWidget(self.sld_filter_sigma_ratio_range, 3, 1)
        chk_layout = QHBoxLayout()
        chk_layout.addWidget(self.chk_filter_sigma_ratio_min)
        chk_layout.addWidget(self.chk_filter_sigma_ratio_max)
        filterLayout.addLayout(chk_layout, 3, 2)
        # 
        filterLayout.addWidget(self.lab_fit_dist_max_err_z_factor, 4, 0)
        filterLayout.addWidget(self.sld_fit_dist_max_err_z_factor, 4, 1)
        filterLayout.addWidget(self.chk_fit_dist_max_err_z_factor, 4, 2)
        # 
        filterLayout.addWidget(self.lab_fit_dist_max_err_xy_factor, 5, 0)
        filterLayout.addWidget(self.sld_fit_dist_max_err_xy_factor, 5, 1)
        filterLayout.addWidget(self.chk_fit_dist_max_err_xy_factor, 5, 2)
        # 
        filterLayout.addWidget(self.lab_min_spot_sep_z_factor, 6, 0)
        filterLayout.addWidget(self.sld_min_spot_sep_z_factor, 6, 1)
        filterLayout.addWidget(self.chk_min_spot_sep_z_factor, 6, 2)
        # 
        filterLayout.addWidget(self.lab_min_spot_sep_xy_factor, 7, 0)
        filterLayout.addWidget(self.sld_min_spot_sep_xy_factor, 7, 1)
        filterLayout.addWidget(self.chk_min_spot_sep_xy_factor, 7, 2)
        # 
        filterLayout.addWidget(self.lab_dist_boundary_z_factor, 8, 0)
        filterLayout.addWidget(self.sld_dist_boundary_z_factor, 8, 1)
        filterLayout.addWidget(self.chk_dist_boundary_z_factor, 8, 2)
        # 
        filterLayout.addWidget(self.lab_dist_boundary_xy_factor, 9, 0)
        filterLayout.addWidget(self.sld_dist_boundary_xy_factor, 9, 1)
        filterLayout.addWidget(self.chk_dist_boundary_xy_factor, 9, 2)
        # chi squared
        filterLayout.addWidget(self.lab_filter_chi_squared, 10, 0)
        filterLayout.addWidget(self.sld_filter_chi_squared, 10, 1)
        filterLayout.addWidget(self.chk_filter_chi_squared, 10, 2)
        filterLayout.addWidget(self.but_filter, 11, 1)
        filterLayout.addWidget(self.but_inspect, 12, 1)
        group_layout.addLayout(filterLayout)

        return group


    def _create_save_groupBox(self):
        group = QGroupBox(title="Save / load")
        group.setCheckable(False)
        # group.setChecked(True)
        group.setSizePolicy(QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum))
        group_layout = QVBoxLayout()
        group.setLayout(group_layout)

        self.but_save_spots = QPushButton()
        self.but_save_spots.setText('Save spots')
        self.but_save_spots.clicked.connect(self._save_spots)
        self.but_load_spots = QPushButton()
        self.but_load_spots.setText('Load spots')
        self.but_load_spots.clicked.connect(self._load_spots)
        self.but_save_parameters = QPushButton()
        self.but_save_parameters.setText('Save detection parameters')
        self.but_save_parameters.clicked.connect(self._save_parameters)
        self.but_load_parameters = QPushButton()
        self.but_load_parameters.setText('Load detection parameters')
        self.but_load_parameters.clicked.connect(self._load_parameters)

        # layout for saving and loading spots data and detection parameters
        saveloadLayout = QGridLayout()
        saveloadLayout.addWidget(self.but_save_spots, 0, 0)
        saveloadLayout.addWidget(self.but_load_spots, 0, 1)
        saveloadLayout.addWidget(self.but_save_parameters, 1, 0)
        saveloadLayout.addWidget(self.but_load_parameters, 1, 1)
        group_layout.addLayout(saveloadLayout)

        return group


    def _get_phy_params(self, theta_as_rad=False):

        na = float(self.txt_na.text())
        ri = float(self.txt_ri.text())
        wvl = float(self.txt_lambda_em.text()) / 1000
        dc = float(self.txt_dc.text())
        dstage = float(self.txt_dstage.text())
        is_skewed = self.chk_skewed.isChecked()
        if is_skewed:
            theta = float(self.txt_angle.text())
            if theta_as_rad:
                theta = theta / 180 * np.pi
        else:
            theta = 0
        return na, ri, wvl, dc, dstage, theta

    def _make_psf(self):

        oversampling = 10
        na, ri, wvl, dc, dstage, theta = self._get_phy_params(theta_as_rad=True)
        psf_model = fit_psf.gridded_psf_model(
            wavelength=wvl,
            ni=ri,
            model_name="vectorial",
            dc=dc / oversampling,
            sf=1,
            # /!\ check about theta's position!
            angles=(0., 0., theta),  # in radians
        )
        # p: ["A", "cx", "cy", "cz", "na", "bg"]
        # "amplitude", "x-coordinate center", "y-coordinate center", "z-coordinate center", "numerical aperture", and "background"
        p = [1, 0, 0, 0, na, 0]
        coords = fit_psf.get_psf_coords(ns=[15, 150, 150], # number of pixels
                                        drs=[dstage, dc / oversampling, dc / oversampling])
        psf = psf_model.model(coords, p)
        # resample image by binning
        bin_size_list = (1,) * (psf.ndim - 2) + (oversampling, oversampling)
        self.psf = camera.bin(psf, bin_size_list, mode='sum')
        self._psf_origin = 'generated'
        print("PSF generated")


    def _load_psf(self):
        
        (filename, _) = QFileDialog.getOpenFileName(
            self, "Select a PSF image", "", "(*.tif *.tiff)"
        )
        if filename:
            self.psf = tifffile.imread(filename)
            self._psf_origin = filename
            print("PSF loaded")


    def _get_selected_image(self):
        if len(self.viewer.layers) == 0:
            print("Open an image first")
        else:
            if len(self.viewer.layers.selection) == 0:
                img = self.viewer.layers[0].data
                scale = self.viewer.layers[0].scale
            else:
                # selection is a set, we need some wrangle to get the first element
                first_selected_layer = next(iter(self.viewer.layers.selection))
                img = first_selected_layer.data
                scale = first_selected_layer.scale
            return img, scale

    def _add_image(self, data, name=None, **kwargs):
        """
        Add or replace an image if already present.
        """
        if name is None:
            self.viewer.add_image(data, **kwargs)
        else:
            if name not in self.viewer.layers:
                self.viewer.add_image(data, name=name, **kwargs)
            else:
                self.viewer.layers[name].data = data

    def _add_points(self, data, name=None, **kwargs):
        """
        Add or replace points if already present.
        """
        if name is None:
            self.viewer.add_points(data, **kwargs)
        else:
            if name not in self.viewer.layers:
                self.viewer.add_points(data, name=name, **kwargs)
            else:
                self.viewer.layers[name].data = data

    def _get_spot3d(self):
        """
        Create an instance of the `SPOT3D` class.
        It includes the image and parameters for analysis.
        Some paramaters will be updated by following steps. 
        """
        img, self.scale = self._get_selected_image()
        na, ri, wvl, dc, dstage, theta = self._get_phy_params()
        metadata = {'pixel_size' : dc,
                    'scan_step' : dstage,
                    'wvl' : wvl}
        microscope_params = {'na' : na,
                             'ri' : ri,
                             'theta' : theta}

        self._spots3d = SPOTS3D(
            data = img,
            psf = self.psf, 
            metadata= metadata,
            microscope_params=microscope_params,
            )
        print("model instanciated")


    def _run_deconvolution(self):
        print("starting deconvolution")
        new_decon_params = {
            'iterations' : int(self.txt_deconv_iter.text()),
            'tv_tau' : float(self.txt_deconv_tvtau.text()),
        }
        self._spots3d.decon_params = new_decon_params
        self._spots3d.scan_chunk_size = 128 # GPU out-of-memory on OPM PC if > 128
        self._spots3d.run_deconvolution()
        print("finished deconvolution")
        self._add_image(data=self._spots3d.decon_data, name='deconv', scale=self.scale)

    def _run_adaptive_histogram(self):
        print('Not implemented yet')

    def _make_sigmas_factors(self):
        """
        Compute min and max of sigmas *factors* x, y and z with traditionnal settings.
        """

        sigma_ratio = float(self.txt_sigma_ratio.text())
        DoG_filter_params = {'sigma_small_x_factor' : 1 / sigma_ratio**(1/2),
                             'sigma_small_y_factor' : 1 / sigma_ratio**(1/2),
                             'sigma_small_z_factor' : 1 / sigma_ratio**(1/2),
                             'sigma_large_x_factor' : 1 * sigma_ratio**(1/2),
                             'sigma_large_y_factor' : 1 * sigma_ratio**(1/2),
                             'sigma_large_z_factor' : 1 * sigma_ratio**(1/2)} 
        self._spots3d.DoG_filter_params = DoG_filter_params
        
        
        self.sld_dog_sigma_x_factor.setValue([DoG_filter_params['sigma_small_x_factor'],
                                              DoG_filter_params['sigma_large_x_factor']])
        self.sld_dog_sigma_y_factor.setValue([DoG_filter_params['sigma_small_y_factor'],
                                              DoG_filter_params['sigma_large_y_factor']])
        self.sld_dog_sigma_z_factor.setValue([DoG_filter_params['sigma_small_z_factor'],
                                              DoG_filter_params['sigma_large_z_factor']])


    def _compute_dog(self):
        """
        Apply a Differential of Gaussian filter on the first image available in Napari.
        """
        if self._spots3d is None:
            print("Setup the spot localization model first.")
        else:
            print("starting DoG filter")
            if self.cbx_dog_choice.currentIndex() == 0:
                self._spots3d.dog_filter_source_data = 'decon'
            else:
                self._spots3d.dog_filter_source_data = 'raw'
            # add choice of chunk size in GUI?
            self._spots3d.scan_chunk_size = 64 # GPU out-of-memory on OPM PC if > 64
            self._spots3d.run_DoG_filter()
            print("finished DoG filter")
            self._add_image(
                data=self._spots3d.dog_data, 
                name='DoG', 
                scale=self.scale,
                # Remark: use _dog_data instead to get the Dask format?
                contrast_limits=[0, self._spots3d.dog_data.max()],
                )


    def _find_peaks(self):
        """
        Threshold the image resulting from the DoG filter and detect peaks.
        """
        if 'DoG' not in self.viewer.layers:
            print("Run a DoG filter on an image first")
        else:
            print("starting find candidates")
            self._spots3d.find_candidates_params = {
                'threshold' : self.sld_dog_thresh.value(),
                'min_spot_xy' : self.sld_min_spot_xy_factor.value(),
                'min_spot_z' : self.sld_min_spot_z_factor.value(),
                }
            self._spots3d.scan_chunk_size = 64 # GPU timeout on OPM if > 64. Will change registry settings for TDM timeout.
            self._spots3d.run_find_candidates()
            print("finished find candidates")

            # # used variables for gaussian fit if peaks are not merged
            # self._peaks_merged = False
            # self._use_centers = self._spots3d._spot_candidates
            # self._use_amps = self._spots3d._amps
            # print(self._spots3d._spot_candidates)
            # print(self._spots3d._spot_candidates.shape) # debug
        
            theta = self._spots3d._image_params['theta'] 
            if (theta > 0) and ('deskewed' not in self.viewer.layers):
                pixel_size = self._spots3d._image_params['pixel_size'] 
                scan_step = self._spots3d._image_params['scan_step'] 
                # deskewed_data = deskew(np.array(self._spots3d._decon_data), pixel_size, scan_step, theta)
                deskewed_data = deskew(self._spots3d.data, pixel_size, scan_step, theta)
                self._add_image(deskewed_data, name='deskewed', scale=[pixel_size, pixel_size, pixel_size])

            self._add_points(
                self._spots3d._spot_candidates[:, :3], 
                name='local maxis',
                blending='additive', 
                size=0.25, 
                face_color='r',
                )


    def _merge_peaks(self):
        """
        Merge peaks that are close to each other.
        """
        print("Separate peak detection and merging not implemented yet")
        # print("Separate local maxima finding and merging not implemented yet")
        # if 'local maxis' not in self.viewer.layers:
        #     print("Find peaks first")
        # else:
        #     print("starting merging peaks")
        #     self._spots3d.run_find_candidates()
        #     print("finished merging peaks")
        #     self._peaks_merged = True
        #     self._use_centers = self._spots3d._spot_candidates[:, :3]
        #     self._use_amps = self._spots3d._spot_candidates[:, :-1]

        #     self._add_points(
        #         self._use_centers, 
        #         name='merged maxis',
        #         blending='additive', 
        #         size=0.25, 
        #         face_color='g',
        #         )
    
    
    def _fit_spots(self):
        """
        Perform a gaussian fitting on each ROI.
        """

        self._spots3d.fit_candidate_spots_params = {
            'n_spots_to_fit' : int(self.txt_n_spots_to_fit.text()),
            'roi_z_factor' : float(self.txt_roi_z_factor.text()),
            'roi_y_factor' : float(self.txt_roi_y_factor.text()),
            'roi_x_factor' : float(self.txt_roi_x_factor.text()),
        }
        print("starting fit spots")
        self._spots3d.run_fit_candidates()
        print("finished fit spots")

        self._centers = self._spots3d._fit_params[:, 3:0:-1]
        self._add_points(self._centers, name='fitted spots', blending='additive', size=0.25, face_color='g')
        print(f"Fitted {len(self._spots3d._fit_params)} spots")

        # process all the results
        self._amplitudes = self._spots3d._fit_params[:, 0]
        self._sigmas_xy = self._spots3d._fit_params[:, 4]
        self._sigmas_z = self._spots3d._fit_params[:, 5]
        self._offsets = self._spots3d._fit_params[:, 6]
        self._chi_squared = self._spots3d._chi_sqrs

        centers_guess = self._spots3d._spot_candidates[:, :3]
        self._dist_fit_xy  = np.sqrt((centers_guess[:, 1] - self._centers[:, 1])**2 +
                                     (centers_guess[:, 2] - self._centers[:, 2])**2) 
        self._dist_fit_z  = np.abs(centers_guess[:, 0] - self._centers[:, 0]) 

        self._sigma_ratios = self._sigmas_z / self._sigmas_xy

        # convert sigma values and distances to factors wrt sigma_z and sigma_xy
        sigma_xy = self._spots3d._sigma_xy
        sigma_z = self._spots3d._sigma_z
        self._sigmas_xy_factors = self._sigmas_xy / sigma_xy
        self._sigmas_z_factors = self._sigmas_z / sigma_z
        self._dist_fit_xy_factors = self._dist_fit_xy / sigma_xy
        self._dist_fit_z_factors = self._dist_fit_z / sigma_z

        # update range of filters
        p_mini = float(self.txt_filter_percentile_min.text())
        p_maxi = float(self.txt_filter_percentile_max.text())
        if self.auto_params:
            self.sld_filter_amplitude_range.setRange(np.percentile(self._amplitudes, p_mini), np.percentile(self._amplitudes, p_maxi))
            self.sld_filter_sigma_xy_factor.setRange(np.percentile(self._sigmas_xy_factors, p_mini), np.percentile(self._sigmas_xy_factors, p_maxi))
            self.sld_filter_sigma_z_factor.setRange(np.percentile(self._sigmas_z_factors, p_mini), np.percentile(self._sigmas_z_factors, p_maxi))
            self.sld_filter_sigma_ratio_range.setRange(np.percentile(self._sigma_ratios, p_mini), np.percentile(self._sigma_ratios, p_maxi))
            self.sld_fit_dist_max_err_z_factor.setRange(np.percentile(self._dist_fit_z_factors, p_mini), np.percentile(self._dist_fit_z_factors, p_maxi))
            self.sld_fit_dist_max_err_xy_factor.setRange(np.percentile(self._dist_fit_xy_factors, p_mini), np.percentile(self._dist_fit_xy_factors, p_maxi))
            # self.sld_min_spot_sep_z_factor.setRange(np.percentile(self._dist_fit_xy, p_mini), np.percentile(self._dist_fit_xy, p_maxi))
            # self.sld_min_spot_sep_xy_factor.setRange(np.percentile(self._dist_fit_z, p_mini), np.percentile(self._dist_fit_z, p_maxi))
            # self.sld_dist_boundary_z_factor.setRange(np.percentile(self._dist_fit_xy, p_mini), np.percentile(self._dist_fit_xy, p_maxi))
            # self.sld_dist_boundary_xy_factor.setRange(np.percentile(self._dist_fit_z, p_mini), np.percentile(self._dist_fit_z, p_maxi))
            self.sld_filter_chi_squared.setRange(np.percentile(self._chi_squared, p_mini), np.percentile(self._chi_squared, p_maxi))
    

    def _plot_fitted_params(self):
        """
        Generate distribution plots of fitted parameters to help selecting
        appropriate threshold values for spot filtering.
        """

        p_mini = float(self.txt_filter_percentile_min.text())
        p_maxi = float(self.txt_filter_percentile_max.text())

        plt.figure()
        plt.hist(self._amplitudes, bins='auto', range=self.sld_filter_amplitude_range.value())
        plt.title("Distribution of amplitude values")

        plt.figure()
        plt.hist(self._sigmas_xy_factors, bins='auto', range=self.sld_filter_sigma_xy_factor.value())
        plt.title("Distribution of sigmas_xy factors")

        plt.figure()
        plt.hist(self._sigmas_z_factors, bins='auto', range=self.sld_filter_sigma_z_factor.value())
        plt.title("Distribution of sigmas_z factors")

        plt.figure()
        plt.hist(self._sigma_ratios, bins='auto', range=self.sld_filter_sigma_ratio_range.value())
        plt.title("Distribution of sigma_ratios values")

        plt.figure()
        plt.hist(self._chi_squared, bins='auto', range=(np.percentile(self._chi_squared, p_mini), 
                                                        np.percentile(self._chi_squared, p_maxi)))
        plt.title("Distribution of chi_squared values")

        plt.figure()
        plt.hist(self._dist_fit_xy_factors, bins='auto', range=(0, 8))
        plt.title("Distribution of dist_fit_xy factors")

        plt.figure()
        plt.hist(self._dist_fit_z_factors, bins='auto', range=(0, 8))
        plt.title("Distribution of dist_fit_z factors")

        plt.show()
    

    def _plot_fitted_params_2D(self):
        """
        Generate 2D distribution plots of fitted parameters to help selecting
        appropriate threshold values for spot filtering.
        """

        p_mini = float(self.txt_filter_percentile_min.text())
        p_maxi = float(self.txt_filter_percentile_max.text())

        distrib = {
            'amplitudes': {'data': self._amplitudes, 
                           'range': self.sld_filter_amplitude_range.value()},
            'sigmas_xy_factors': {'data': self._sigmas_xy_factors, 
                                  'range': self.sld_filter_sigma_xy_factor.value()},
            'sigmas_z_factors': {'data': self._sigmas_z_factors, 
                                 'range': self.sld_filter_sigma_z_factor.value()},
            'sigma_ratios': {'data': self._sigma_ratios, 
                             'range': self.sld_filter_sigma_ratio_range.value()},
            'chi_squared': {'data': self._chi_squared, 
                            'range': (np.percentile(self._chi_squared, p_mini), 
                                      np.percentile(self._chi_squared, p_maxi))},
            'dist_fit_xy_factors': {'data': self._dist_fit_xy_factors, 
                                    'range': (np.percentile(self._dist_fit_xy_factors, p_mini), 
                                              np.percentile(self._dist_fit_xy_factors, p_maxi))},
            'dist_fit_z_factors': {'data': self._dist_fit_z_factors, 
                                   'range': (np.percentile(self._dist_fit_z_factors, p_mini), 
                                             np.percentile(self._dist_fit_z_factors, p_maxi))},
        }
        
        var_labels = list(distrib.keys())
        var_combi = itertools.combinations(var_labels, 2)
        for var_x, var_y in var_combi:
            x_mini, x_maxi = distrib[var_x]['range']
            y_mini, y_maxi = distrib[var_y]['range']
            x_select = np.logical_and(distrib[var_x]['data'] >= x_mini, distrib[var_x]['data'] <= x_maxi)
            y_select = np.logical_and(distrib[var_y]['data'] >= y_mini, distrib[var_y]['data'] <= y_maxi)
            select = np.logical_and(x_select, y_select)
            x_data = distrib[var_x]['data'][select]
            y_data = distrib[var_y]['data'][select]

            plt.figure()
            plt.scatter(x_data, y_data, s=10, marker='.', c='b', alpha=0.5)
            plt.title(f"Distributions of {var_x} and {var_y}")
            plt.xlabel(var_x)
            plt.ylabel(var_y)
            plt.show()


    def _filter_spots(self):
        """
        Filter out spots based on gaussian fit results.
        """

        # list of boolean filters for all spots thresholds
        selectors = []

        spot_filter_params = {
            'amp_min' : self.sld_filter_amplitude_range.value()[0],
            'sigma_min_z_factor' : self.sld_filter_sigma_z_factor.value()[0],
            'sigma_min_xy_factor' : self.sld_filter_sigma_xy_factor.value()[0],                     
            'sigma_max_z_factor' : self.sld_filter_sigma_z_factor.value()[1],
            'sigma_max_xy_factor' : self.sld_filter_sigma_xy_factor.value()[1],
            'fit_dist_max_err_z_factor': self.sld_fit_dist_max_err_z_factor.value(),
            'fit_dist_max_err_xy_factor': self.sld_fit_dist_max_err_xy_factor.value(),
            'min_spot_sep_z_factor' : self.sld_min_spot_sep_z_factor.value(),
            'min_spot_sep_xy_factor' : self.sld_min_spot_sep_xy_factor.value(),
            'dist_boundary_z_factor' : self.sld_dist_boundary_z_factor.value(),
            'dist_boundary_xy_factor' : self.sld_dist_boundary_xy_factor.value(),
            'min_sigma_ratio' : self.sld_filter_sigma_ratio_range.value()[0],
            'max_sigma_ratio' : self.sld_filter_sigma_ratio_range.value()[1],
        }
        self._spots3d.spot_filter_params = spot_filter_params
        print("starting filter spots")
        self._spots3d.run_filter_spots()
        print("finished filter spots")

        self._spot_select = self._spots3d._to_keep
        self._centers_fit_masked = self._centers[self._spot_select, :]
        nb_kept = self._spots3d._to_keep.sum()
        print(f"Selected {nb_kept} spots out of {len(self._spots3d._to_keep)} candidates")
        self._add_points(self._centers_fit_masked, name='filtered spots', blending='additive', size=0.25, face_color='b')

        
    def _inspect_filtering(self):

        if self._centers_fit_masked is None:
            print("Filter fitted spots first.")
        else:
            # condition_beads is the nfits x nfilters array telling which spots failed
            # init_params_beads is the nfits x nparameters array of initial parameters

            condition_names = self._spots3d._condition_names
            conditions_beads = self._spots3d._conditions
            to_keep_beads = self._spots3d._to_keep
            init_params_beads = self._spots3d._spot_candidates[:, :3]
            roi_inds = np.arange(len(to_keep_beads))

            strs = ["\n".join([condition_names[aa] for aa, c in enumerate(cs) if not c])
            for ii, cs in enumerate(conditions_beads) if not to_keep_beads[ii]]

            centers_init_beads = init_params_beads#[:, (3, 2, 1)]
            cs = centers_init_beads[np.logical_not(to_keep_beads)]

            # TODO: fix orientation between raw and deskewed data
            self._add_points(
                cs,
                symbol="disc",
                name="centers rejected",
                out_of_slice_display=False,
                opacity=1,
                face_color=[0, 0, 0, 0],
                edge_color=[0, 1, 0, 1],
                size=self._spots3d._spot_filter_params['min_spot_sep'][1],
                features={"rejection_reason": strs},
                        #"roi_number": roi_inds_beads[np.logical_not(to_keep_beads)]},
                text={'string': '{rejection_reason}',
                    'size': 100 * self.scale[1],
                    'color': 'white',
                    # avoid translation as it doesn't adapt dynamically when switching between 2D and 3D views
                    # 'translation': np.array([self._spots3d._fit_candidate_spots_params['roi_y'] / 2, 
                    #                          self._spots3d._fit_candidate_spots_params['roi_x'] / 2]),
                    },
            )
            

    def _save_spots(self):

            # save the results
            if not hasattr(self, '_spot_select'):
                self._spot_select = np.full(len(self._centers), np.nan)
            if self._centers.shape[1] == 3:
                df_spots = pd.DataFrame({
                    'amplitudes': self._amplitudes,
                    'z': self._centers[:,0],
                    'y': self._centers[:,1],
                    'x': self._centers[:,2],
                    'sigmas_xy': self._sigmas_xy,
                    'sigmas_z': self._sigmas_z,
                    'offsets': self._offsets,
                    'chi_squareds': self._chi_squared,
                    'dist_fit_xy': self._dist_fit_xy,
                    'dist_fit_z': self._dist_fit_z,
                    'spot_select': self._spot_select,
                })
            else:
                df_spots = pd.DataFrame({
                    'amplitudes': self._amplitudes,
                    'y': self._centers[:,1],
                    'x': self._centers[:,2],
                    'sigmas_xy': self._sigmas_xy,
                    'sigmas_z': self._sigmas_z,
                    'offsets': self._offsets,
                    'chi_squareds': self._chi_squared,
                    'dist_fit_xy': self._dist_fit_xy,
                    'dist_fit_z': self._dist_fit_z,
                    'spot_select': self._spot_select,
                })

            path_save = QFileDialog.getSaveFileName(self, 'Export spots data')[0]
            if path_save != '':
                if not path_save.endswith('.csv'):
                    path_save = path_save + '.csv'
                df_spots.to_csv(path_save, index=False)


    def _load_spots(self):

        path_load = QFileDialog.getOpenFileName(self,"Load spots data","","CSV Files (*.csv);;All Files (*)")[0]
        if path_load != '':
            df_spots = pd.read_csv(path_load)
            self._amplitudes = df_spots['amplitudes']
            self._sigmas_xy = df_spots['sigmas_xy']
            self._offsets = df_spots['offsets']
            self._chi_squareds = df_spots['chi_squareds']
            self._dist_center = df_spots['dist_center']
            self._spot_select = df_spots['spot_select']
            if 'z' in df_spots.columns:
                self._centers = np.zeros((len(df_spots['x']), 3))
                self._centers[:, 0] = df_spots['z']
                self._centers[:, 1] = df_spots['y']
                self._centers[:, 2] = df_spots['x']
                self._sigmas_z = df_spots['sigmas_z']
                self._sigma_ratios = self._sigmas_z / self._sigmas_xy
            else:
                self._centers = np.zeros((len(df_spots['x']), 2))
                self._centers[:, 0] = df_spots['y']
                self._centers[:, 1] = df_spots['x']
            
            self._add_points(self._centers, name='fitted spots', blending='additive', size=0.25, face_color='g')
            # display filtered spots if there was a filtering
            if ~np.all(self._spot_select.isna()):
                self._add_points(self._centers[self._spot_select], name='filtered spots', blending='additive', size=0.25, face_color='b')


    def _save_parameters(self):

        detection_parameters = {
            'metadata': self._spots3d.metadata,
            'microscope_params': self._spots3d.microscope_params,
            'decon_params': self._spots3d.decon_params,
            'dog_filter_source_data': self._spots3d.dog_filter_source_data,
            'DoG_filter_params': self._spots3d.DoG_filter_params,
            'find_candidates_params': self._spots3d.find_candidates_params,
            'fit_candidate_spots_params': self._spots3d.fit_candidate_spots_params,
            'spot_filter_params': self._spots3d.spot_filter_params,
            'psf_origin': self._psf_origin,
        }

        path_save = QFileDialog.getSaveFileName(self, 'Export detection parameters')[0]
        if path_save != '':
            if not path_save.endswith('.json'):
                path_save = path_save + '.json'
            with open(path_save, "w") as write_file:
                json.dump(detection_parameters, write_file, indent=4)


    def _load_parameters(self):

        path_load = QFileDialog.getOpenFileName(self,"Load spots data","","JSON Files (*.json);;All Files (*)")[0]
        if path_load != '':
            # deactivate automatic parameters update during pipeline execution
            self.auto_params = False
            with open(path_load, "r") as read_file:
                detection_parameters = json.load(read_file)
            
            # parse all keys and modify the widgets' values
            self.txt_na.setText(str(detection_parameters['microscope_params']['na']))
            self.txt_ri.setText(str(detection_parameters['microscope_params']['ri']))
            self.txt_lambda_em.setText(str(int(detection_parameters['metadata']['wvl'] * 1000)))
            self.txt_dc.setText(str(detection_parameters['metadata']['pixel_size']))
            self.txt_dstage.setText(str(detection_parameters['metadata']['scan_step']))
            theta = float(detection_parameters['microscope_params']['theta'])
            if theta > 0:
                self.chk_skewed.setChecked(True)
                self.txt_angle.setText(str(theta))
            else:
                self.chk_skewed.setChecked(False)
            
            if detection_parameters['psf_origin'] == 'generated':
                self._make_psf()
                self._psf_origin = 'generated'
            else:
                try:
                    self.psf = tifffile.imread(detection_parameters['psf_origin'])
                    self._psf_origin = detection_parameters['psf_origin']
                    print("PSF loaded from", self._psf_origin)
                except FileNotFoundError:
                    print("PSF couldn't be loaded because file was not found at", detection_parameters['psf_origin'])
            
            self.txt_deconv_iter.setText(str(detection_parameters['decon_params']['iterations']))
            self.txt_deconv_tvtau.setText(str(detection_parameters['decon_params']['tv_tau']))
            # self.txt_adapthist_x.setText(str(detection_parameters['']))  # not implemented yet
            # self.txt_adapthist_y.setText(str(detection_parameters['']))
            # self.txt_adapthist_z.setText(str(detection_parameters['']))
            
            self.sld_dog_sigma_x_factor.setRange(detection_parameters['DoG_filter_params']['sigma_small_x_factor'],
                                                  detection_parameters['DoG_filter_params']['sigma_large_x_factor'])
            self.sld_dog_sigma_y_factor.setRange(detection_parameters['DoG_filter_params']['sigma_small_y_factor'],
                                                  detection_parameters['DoG_filter_params']['sigma_large_y_factor'])
            self.sld_dog_sigma_z_factor.setRange(detection_parameters['DoG_filter_params']['sigma_small_z_factor'],
                                                  detection_parameters['DoG_filter_params']['sigma_large_z_factor'])
            self.sld_dog_thresh.setValue(detection_parameters['find_candidates_params']['threshold'])
            if detection_parameters['dog_filter_source_data'] == 'decon':
                self.cbx_dog_choice.setCurrentIndex(0)
            else:
                self.cbx_dog_choice.setCurrentIndex(1)
            self.sld_min_spot_xy_factor.setValue(detection_parameters['find_candidates_params']['min_spot_xy_factor'])
            self.sld_min_spot_z_factor.setValue(detection_parameters['find_candidates_params']['min_spot_z_factor'])
            
            self.txt_n_spots_to_fit.setText(str(detection_parameters['fit_candidate_spots_params']['n_spots_to_fit']))
            self.txt_roi_z_factor.setText(str(detection_parameters['fit_candidate_spots_params']['roi_z_factor']))
            self.txt_roi_y_factor.setText(str(detection_parameters['fit_candidate_spots_params']['roi_y_factor']))
            self.txt_roi_x_factor.setText(str(detection_parameters['fit_candidate_spots_params']['roi_x_factor']))

            self.sld_filter_amplitude_range.setRange(detection_parameters['spot_filter_params']['amp_min'],
                                                      detection_parameters['spot_filter_params']['amp_min'] * 500) # amp max not considered actually
            self.sld_filter_sigma_xy_factor.setRange(detection_parameters['spot_filter_params']['sigma_min_xy_factor'],
                                                     detection_parameters['spot_filter_params']['sigma_max_xy_factor'])
            self.sld_filter_sigma_z_factor.setRange(detection_parameters['spot_filter_params']['sigma_min_z_factor'],
                                                    detection_parameters['spot_filter_params']['sigma_max_z_factor'])
            try:
                self.sld_filter_sigma_ratio_range.setRange((detection_parameters['spot_filter_params']['min_sigma_ratio'], 
                                                            detection_parameters['spot_filter_params']['min_sigma_ratio']))
            except:
                print("There was no sigma_ratio boundaries defined")
            self.sld_fit_dist_max_err_z_factor.setValue(detection_parameters['spot_filter_params']['fit_dist_max_err_z_factor'])
            self.sld_fit_dist_max_err_xy_factor.setValue(detection_parameters['spot_filter_params']['fit_dist_max_err_xy_factor'])
            self.sld_min_spot_sep_z_factor.setValue(detection_parameters['spot_filter_params']['min_spot_sep_z_factor'])
            self.sld_min_spot_sep_xy_factor.setValue(detection_parameters['spot_filter_params']['min_spot_sep_xy_factor'])
            self.sld_dist_boundary_z_factor.setValue(detection_parameters['spot_filter_params']['dist_boundary_z_factor'])
            self.sld_dist_boundary_xy_factor.setValue(detection_parameters['spot_filter_params']['dist_boundary_xy_factor'])
            # self.sld_filter_chi_squared.setValue(detection_parameters[''])  # not implemented yet
            print("Parameters loaded")

            

if __name__ == "__main__":
    viewer = napari.Viewer()
    napari.run()

# TODO:
#   - all functions compatible with 2D data
#   - add raw estimation of spots parameters by drawing box around one spot and estimating (fitting gaussian?) parameters
#   - add check on individual ROIs
#   - add panel to select data from big images, random tile, specific channel, etc...
#   - add manual annotation and automatic training for filtering parameters