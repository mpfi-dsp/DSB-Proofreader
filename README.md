# DSB Proofreader

The DSB project is split into two repositories. The [first repository](https://www.github.com/alexanderjcs/dsb-plugin) is a Dragonfly 3D World plugin, which processes neuron data to find dendritic spine head center locations. The second repository (this one) proofreads the proposed head centers and computes a radius measurement.

The input for this program is a `.dsb` file, which is acquired from the DSB Dragonfly Plugin. It outputs a CSV containing the head center names, radii, 3D positions, index, and label (assigned by a human proofreader).

## Installation

Please see the installation instructions [here](INSTALL.md).

## User Guide

See the user guide [here](USER_GUIDE.md).
