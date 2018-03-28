#!/usr/bin/env python

import os, platform, sys, glob, argparse, datetime
import pandas, tifffile, numpy
from taniclass import spotplotter, bfchaser, spotfilter

# prepare classes
plotter = spotplotter.SpotPlotter()
chaser = bfchaser.BFChaser()
filter = spotfilter.SpotFilter()

# defaults
input_filenames = None
image_size = None
align_spots = True
align_filename = 'align.txt'
output_filename = 'plot_%s.tif' % datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
output_stackmode = None
output_stackeach = 1
chase_spots = False
lifetime_range = [1, 0]
consolidate_spots = False
consolidate_mode_choices = ['average', 'first', 'last']
consolidate_mode = consolidate_mode_choices[0]

# parse arguments
parser = argparse.ArgumentParser(description='make super-resolution image from spot centroids.', \
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument('-o', '--output-file', nargs=1, default=[output_filename], \
                    help='output super-resolution tiff file')

parser.add_argument('-l', '--lifetime-range', nargs=2, type=int, default=lifetime_range, \
                    metavar=('MIN', 'MAX'), \
                    help='range of spot lifetime (set MAX = 0 for numpy.inf)')

parser.add_argument('-s', '--consolidate-spots', action='store_true', default=consolidate_spots, \
                    help='consolidate centroids for chased spots')
parser.add_argument('-m', '--consolidate-mode', nargs=1, default=[consolidate_mode], \
                    choices = consolidate_mode_choices, \
                    help='consolidation mode for chased spots')

parser.add_argument('-n', '--no-align', action='store_true', default=(align_spots is False), \
                    help='plot without alignment')
parser.add_argument('-a', '--align-file', nargs=1, default=[align_filename], \
                    help='tsv file with alignment (align.txt if not specified)')
parser.add_argument('-e', '--align-each', nargs=1, type=int, default=[plotter.align_each], \
                    help='alignment correction every X plane')
                    
parser.add_argument('-x', '--image-scale', nargs=1, type=int, default=[plotter.image_scale], \
                    help='scale factor to original image')
parser.add_argument('-z', '--image-size', nargs=2, type=int, default=image_size, \
                    metavar=('WIDTH', 'HEIGHT'), \
                    help='size of original image (read from first file if not specified)')

parser.add_argument('-C', '--chase-spots', action='store_true', default=chase_spots, \
                    help='chase spots before output tsv file')
parser.add_argument('-d', '--chase-distance', nargs=1, type=float, default = [chaser.chase_distance], \
                    help='maximum distance to assume as identical spots (pixel)')

group = parser.add_mutually_exclusive_group()
group.add_argument('-T', '--seperate-stack', action='store_const', \
                    dest='output_stackmode', const='separate', \
                    help='output using separated stack')
group.add_argument('-U', '--cumulative-stack', action='store_const', \
                    dest='output_stackmode', const='cumulative', \
                    help='output using cumulative stack')

parser.add_argument('-E', '--stack-each', nargs=1, type=int, default=[output_stackeach], \
                    help='stack every X file')

parser.add_argument('input_file', nargs='+', default=None, \
                    help='input tsv file(s) with plotting geometries')

args = parser.parse_args()

# collect input filenames
if (platform.system() == "Windows"):
    input_filenames = []
    for pattern in args.input_file:
        input_filenames.extend(sorted(glob.glob(pattern)))
    if len(input_filenames) == 0:
        raise Exception('no input filename')
else:
    input_filenames = args.input_file

# set arguments
align_spots = (args.no_align is False)
align_filename = args.align_file[0]
image_size = args.image_size
output_stackmode = args.output_stackmode
output_stackeach = args.stack_each[0]

plotter.align_each = args.align_each[0]
plotter.image_scale = args.image_scale[0]
chase_spots = args.chase_spots
chaser.chase_distance = args.chase_distance[0]

lifetime_range = args.lifetime_range
consolidate_spots = args.consolidate_spots
consolidate_mode = args.consolidate_mode[0]

# read align table
if align_spots is True:
    align_table = pandas.read_table(align_filename, comment = '#')
    print("Using %s for alignment." % (align_filename))
else:
    align_table = None

# read first table and determine size
if image_size is None:
    width, height = plotter.read_image_size(input_filenames[0])
else:
    width, height = image_size[0], image_size[1]

# prepare output image
output_image = numpy.zeros((height * plotter.image_scale, width * plotter.image_scale), dtype=numpy.int64)
if output_stackmode is not None:
    stack_size = ((len(input_filenames) - 1) // output_stackeach) + 1
    output_stack = numpy.zeros((stack_size, \
                                height * plotter.image_scale, width * plotter.image_scale), \
                                dtype=numpy.int64)

# plot spots for each table
last_plane = 0

for index, input_filename in enumerate(input_filenames):
    # init output image for separate stack
    if output_stackmode == 'separate':
        output_image = 0

    # get parameters and spots
    params = plotter.read_image_params(input_filename)
    spot_table = pandas.read_csv(input_filename, sep='\t', comment='#')
    
    # chase if necessary
    if chase_spots is True:
        if 'distance' in spot_table.columns:
            print("Skip chasing in %s (already chased)." % (input_filename))
        else:
            print("Total %d spots in %s." % (len(spot_table), input_filename))
            spot_table = chaser.chase_spots(spot_table)
            print("Chaser detected %d unique spots." % (len(spot_table.total_index.unique())))

    # add lifetime (added here for easier debug)
    spot_table = filter.add_lifetime(spot_table)

    # filter using lifetime of spots
    if lifetime_range != [1, 0]:
        total_spots = len(spot_table)
        filter.lifetime_min = lifetime_range[0]
        filter.lifetime_max = [numpy.inf if lifetime_range[1] == 0 else lifetime_range[1]]
        spot_table = filter.filter_spots_lifetime(spot_table)
        print("Filtered %d of %d spots." % (total_spots - len(spot_table), total_spots))

    # average cenroids
    if consolidate_spots is True:
        total_spots = len(spot_table)
        if consolidate_mode == 'average':
            spot_table = filter.average_spots(spot_table)
        elif consolidate_mode == 'first':
            spot_table = filter.keep_first_spots(spot_table)
        elif consolidate_mode == 'last':
            spot_table = filter.keep_last_spots(spot_table)
        else:
            raise Exception('unknown consolidation mode')
        print("Consolidated (%s) to %d of %d spots." % (consolidate_mode, len(spot_table), total_spots))

    # plot
    print(spot_table)
    output_image = plotter.plot_spots(output_image, last_plane, spot_table, align_table)
    
    # save into stack
    if output_stackmode is not None:
        if index % output_stackeach == 0:
            output_stack[index // output_stackeach] = output_image
    
    last_plane += params['total_planes']
    
    print("Plot %d spots (%d planes) from %s." % (len(spot_table), params['total_planes'], input_filename))

# save into last stack
if output_stackmode is not None:
    if index % output_stackeach != 0:
        output_stack[-1] = output_image


# output (multipage) tiff
if output_stackmode is None:
    # clip output.tif to 32bit and output
    print("Output image file to %s." % (output_filename))
    output_image_32bit = output_image.clip(0, numpy.iinfo(numpy.int32).max).astype(numpy.int32)
    tifffile.imsave(output_filename, output_image_32bit)
else:
    # clip output.tif to 32bit and output
    print("Output %s stack image file to %s." % (output_stackmode, output_filename))
    output_image_32bit = output_stack.clip(0, numpy.iinfo(numpy.int32).max).astype(numpy.int32)
    tifffile.imsave(output_filename, output_image_32bit)

