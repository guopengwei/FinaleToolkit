"""
Author: James Li
Created: 6/2/23
PI: Yaping Liu

Description:
Python script to calculate fragment features given a BAM file.

"""
# TODO: typing annotations for all functions

from __future__ import annotations
import argparse
import gzip
import time
import os
import tempfile as tf
from multiprocessing.pool import Pool
from typing import Union, TextIO, BinaryIO

import pysam
import numpy as np
from numba import jit
from tqdm import tqdm
from finaletools.utils import (
    frag_bam_to_bed,
    frag_array,
    not_read1_or_low_quality
)

from finaletools.frag.frag_length import frag_length
from finaletools.frag.coverage import frag_center_coverage


@jit(nopython=True)
def _single_wps(window_start: int,
                window_stop: int,
                window_position: int,
                frag_ends: np.ndarray
                ) -> tuple:
    # count number of totally spanning fragments
    is_spanning = ((frag_ends[:, 0] < window_start)
                   * (frag_ends[:, 1] > window_stop))
    num_spanning = np.sum(is_spanning)

    # count number of fragments with end in window
    is_start_in = ((frag_ends[:, 0] >= window_start)
                   * (frag_ends[:, 0] <= window_stop))
    is_stop_in = ((frag_ends[:, 1] >= window_start)
                  * (frag_ends[:, 1] <= window_stop))
    is_end_in = np.logical_or(is_start_in, is_stop_in)
    num_end_in = np.sum(is_end_in)

    # calculate wps and return
    return (window_position, num_spanning - num_end_in)



@jit(nopython=True)
def _vectorized_wps(frag_ends, window_starts, window_stops):
    """
    Unused helper function for vectorization
    """


    w_starts = np.column_stack(window_starts)
    w_stops = np.column_stack(window_stops)
    frag_starts = np.row_stack(frag_ends[:, 0])
    frag_stops = np.row_stack(frag_ends[:, 1])

    is_spanning = np.logical_and(
            np.less_equal(frag_starts, w_starts),
            np.greater_equal(frag_stops, w_stops))

    n_spanning = np.sum(is_spanning, axis=0)

    start_in = np.logical_and(
        np.less(frag_starts, w_starts),
        np.greater_equal(frag_starts, w_stops))

    stop_in = np.logical_and(
        np.less(frag_stops, w_starts),
        np.greater_equal(frag_stops, w_stops))

    end_in = np.logical_or(start_in, stop_in)

    n_end_in = np.sum(end_in, axis=0)

    scores = n_spanning - n_end_in

    return scores


@jit(nopython=True)
def _wps_loop(frag_ends: np.ndarray,
              start: int,
              stop: int,
              window_size: int):
    # array to store positions and scores
    scores = np.zeros((stop-start, 2))
    window_centers = np.arange(start, stop, dtype=np.int64)
    scores[:, 0] = window_centers
    window_starts = np.zeros(stop-start)
    window_stops = np.zeros(stop-start)
    np.rint(window_centers - window_size * 0.5, window_starts)
    np.rint(window_centers + window_size * 0.5 - 1, window_stops)
    # inclusive

    for i in range(stop-start):
        scores[i, :] = _single_wps(
            window_starts[i],
            window_stops[i],
            window_centers[i],
            frag_ends)

    return scores


def wps(input_file: Union[str, pysam.AlignmentFile],
        contig: str,
        start: Union[int, str],
        stop: Union[int, str],
        output_file: str=None,
        window_size: int=120,
        fraction_low: int=120,
        fraction_high: int=180,
        quality_threshold: int=30,
        verbose: Union[bool, int]=0
        ) -> np.ndarray:
    """
    Return Windowed Protection Scores as specified in Snyder et al
    (2016) over a region [start,stop).

    Parameters
    ----------
    input_file : str or pysam.AlignmentFile
        BAM or SAM file containing paired-end fragment reads or its
        path. `AlignmentFile` must be opened in read mode.
    contig : str
    start : int
    stop : int
    output_file : string, optional
    window_size : int, optional
        Size of window to calculate WPS. Default is k = 120, equivalent
        to L-WPS.
    fraction_low : int, optional
        Specifies lowest fragment length included in calculation.
        Default is 120, equivalent to long fraction.
    fraction_high : int, optional
        Specifies highest fragment length included in calculation.
        Default is 120, equivalent to long fraction.
    quality_threshold : int, optional
    workers : int, optional
    verbose : bool, optional

    Returns
    -------
    scores : numpy.ndarray
        np array of shape (n, 2) where column 1 is the coordinate and
        column 2 is the score and n is the number of coordinates in
        region [start,stop)
    """

    if (verbose):
        start_time = time.time()
        print("Reading fragments")

    # set start and stop to ints
    start = int(start)
    stop = int(stop)

    # set minimum and maximum values for fragments. These extend farther
    # than needed
    minimum = round(start - fraction_high)
    maximum = round(stop + fraction_high)

    # read fragments from file
    frag_ends = frag_array(input_file,
                           contig,
                           quality_threshold,
                           minimum=minimum,
                           maximum=maximum,
                           fraction_low=fraction_low,
                           fraction_high=fraction_high,
                           verbose=(verbose>=2))

    if (verbose):
        print("Done reading fragments, preparing for WPS calculation.")
    # check if no fragments exist on this interval
    if (frag_ends.shape == (0, 2)):

        scores = np.zeros((stop-start, 2))
        scores[:, 0] = np.arange(start, stop, dtype=int)
    else:
        scores = _wps_loop(frag_ends, start, stop, window_size)


    # TODO: consider switch-case statements and determine if they
    # shouldn't be used for backwards compatability
    if (type(output_file) == str):   # check if output specified

        if (verbose):
            print('Writing to output file.')

        if output_file.endswith(".wig.gz"): # zipped wiggle
            with gzip.open(output_file, 'wt') as out:
                # declaration line
                out.write(
                    f'fixedStep\tchrom={contig}\tstart={start}\t'
                    f'step={1}\tspan={stop-start}\n'
                    )
                for score in scores[:, 1]:
                    out.write(f'{score}\n')

        elif output_file.endswith(".wig"):  # wiggle
            with open(output_file, 'wt') as out:
                # declaration line
                out.write(
                    f'fixedStep\tchrom={contig}\tstart={start}\tstep='
                    f'{1}\tspan={stop-start}\n'
                    )
                for score in scores[:, 1]:
                    out.write(f'{score}\n')

        else:   # unaccepted file type
            raise ValueError(
                'output_file can only have suffixes .wig or .wig.gz.'
                )

    elif (output_file is not None):
        raise TypeError(
            f'output_file is unsupported type "{type(input_file)}". '
            'output_file should be a string specifying the path of the file '
            'to output scores to.'
            )

    if (verbose):
        end_time = time.time()
        print(f'wps took {end_time - start_time} s to complete')

    return scores


def _agg_wps_single_contig(input_file: Union[str, str],
                           contig: str,
                           site_bed: str,
                           window_size: int=120,
                           size_around_sites: int=5000,
                           fraction_low: int=120,
                           fraction_high: int=180,
                           quality_threshold: int=30,
                           verbose: Union[int, bool]=0
                           ):
    """
    Helper function for aggregate_wps. Aggregates wps over sites in one
    contig.

    Parameters
    ----------
    input_file : str or pysam.AlignmentFile
        BAM or SAM file containing paired-end fragment reads or its
        path. `AlignmentFile` must be opened in read mode.
    contig : str
    window_size : int, optional
        Size of window to calculate WPS. Default is k = 120, equivalent
        to L-WPS.
    quality_threshold : int, optional
    workers : int, optional
    verbose : int or bool, optional

    Returns
    -------
    scores : numpy.ndarray
        np array of shape (window_size, 2) where column 1 is the coordinate and
        column 2 is the score.
    """
    if verbose:
        print(f'Aggregating over contig {contig}...')

    # Create tempfile and write contig fragments to
    print(f'Creating frag bed for {contig}')
    try:
        _, frag_bed = tf.mkstemp(suffix='.bed.gz', text=True)
        frag_bam_to_bed(input_file,
                        frag_bed,
                        contig=None,
                        quality_threshold=30,
                        verbose=False)

        scores = np.zeros((size_around_sites, 2))

        # Values to add to center of each site to get start and stop of each
        # wps function
        left_of_site = round(-size_around_sites / 2)
        right_of_site = round(size_around_sites / 2)

        assert right_of_site - left_of_site == size_around_sites
        scores[:, 0] = np.arange(left_of_site, right_of_site)

        unaggregated_scores = []

        if (verbose):
            print(f'Opening {input_file} for {contig}...')

        if (verbose >= 2):
            with open(site_bed, 'rt') as sites:
                print('File opened! counting lines for {contig}')
                bed_length = 0
                for line in sites:
                    bed_length += 1
        with open(site_bed, 'rt') as sites:
            # verbose stuff
            if (verbose):
                print(f'File opened! Iterating through sites for {contig}...')

            # aggregate wps over sites in bed file
            for line in (
                tqdm(sites, total=bed_length) if verbose>=2 else sites
                ):
                line_items = line.split()
                if ('.' in line_items[5] or contig not in line_items[0]):
                    continue
                single_scores = wps(frag_bed,
                                    line_items[0],
                                    int(line_items[1]) + left_of_site,
                                    int(line_items[1]) + right_of_site,
                                    output_file=None,
                                    window_size=window_size,
                                    fraction_low=fraction_low,
                                    fraction_high=fraction_high,
                                    quality_threshold=quality_threshold,
                                    verbose=(verbose-2 if verbose-2>0 else 0)
                                    )[:, 1]

                if ('+' in line_items[5]):
                    unaggregated_scores.append(single_scores)
                elif ('-' in line_items[5]):
                    single_scores = np.flip(single_scores)
                    unaggregated_scores.append(single_scores)
                else:   # sites without strand direction are ignored
                    pass
            scores[:, 1] = np.sum(unaggregated_scores, axis=0)
    except Exception as e:
        print(e)
    finally:
        os.remove(frag_bed)
    if (verbose):
        print(f'Aggregation complete for {contig}!', flush=True)

    return scores


def _agg_wps_process(bam,
                     contig,
                     tss,
                     window_size,
                     size_around_sites,
                     fraction_low,
                     fraction_high,
                     quality_threshold):
    min = tss - 2 * window_size - size_around_sites // 2
    minimum = min if min >= 0 else 0
    maximum = tss + 2 * window_size + size_around_sites // 2

    frag_ends = frag_array(bam,
                           contig,
                           quality_threshold,
                           minimum,
                           maximum,
                           fraction_low,
                           fraction_high)

    start = tss - size_around_sites // 2
    stop = tss + size_around_sites // 2

    scores = _wps_loop(frag_ends, start, stop, window_size)
    return scores


def aggregate_wps(input_file: Union[pysam.AlignmentFile, str],
                  site_bed: str,
                  output_file: str=None,
                  window_size: int=120,
                  size_around_sites: int=5000,
                  fraction_low: int=120,
                  fraction_high: int=180,
                  quality_threshold: int=30,
                  workers: int=1,
                  verbose: Union[bool, int]=0
                  ) -> np.ndarray:
    """
    Function that aggregates WPS over sites in BED file
    """
    if (verbose):
        start_time = time.time()
        print(
            f"""
            Calculating aggregate WPS
            input_file: {input_file}
            site_bed: {site_bed}
            output_file: {output_file}
            window_size: {window_size}
            size_around_sites: {size_around_sites}
            quality_threshold: {quality_threshold}
            workers: {workers}
            verbose: {verbose}
            """
            )

    """
    with open(site_bed) as bed_file:
        contigs = []
        for line in bed_file:
            contig = line.split()[0].strip()
            if contig not in contigs:
                contigs.append(contig)

        num_contigs = len(contigs)


    if (verbose):
        print(f'Fragments for {num_contigs} contigs detected.')

    if (verbose >= 2):
        for contig in contigs:
            print(contig)

    input_tuples = zip([input_file] * num_contigs,
                       contigs,
                       [site_bed] * num_contigs,
                       [window_size] * num_contigs,
                       [size_around_sites] * num_contigs,
                       [fraction_low] * num_contigs,
                       [fraction_high] * num_contigs,
                       [quality_threshold] * num_contigs,
                       [verbose - 1 if verbose >= 1 else 0] * num_contigs)

    if (verbose):
        print('Calculating...')

    with Pool(workers) as pool:
        contig_scores = pool.starmap(_agg_wps_single_contig, input_tuples)

    if (verbose):
        print('Compiling scores')
    """
    # read tss contigs and coordinates from bed
    contigs = []
    ts_sites = []
    with open(site_bed) as bed:
        for line in bed:
            contents = line.split()
            contig = contents[0].strip()
            start = int(contents[1])
            contigs.append(contig)
            ts_sites.append(start)


    left_of_site = round(-size_around_sites / 2)
    right_of_site = round(size_around_sites / 2)

    assert right_of_site - left_of_site == size_around_sites


    starts = [tss+left_of_site for tss in ts_sites]
    stops = [tss+right_of_site for tss in ts_sites]

    count = len(contigs)

    tss_list = zip(
        count*[input_file],
        contigs,
        starts,
        stops,
        count*[None],
        count*[window_size],
        count*[fraction_low],
        count*[fraction_high],
        count*[quality_threshold])

    with Pool(workers) as pool:
        contig_scores = pool.starmap(wps, tss_list)

    scores = np.zeros((size_around_sites, 2))

    scores[:, 0] = np.arange(left_of_site, right_of_site)

    for contig_score in contig_scores:
        scores[:, 1] = scores[:, 1] + contig_score[:, 1]

    if (type(output_file) == str):   # check if output specified
        if (verbose):
            print(f'Output file {output_file} specified. Opening...')
        if output_file.endswith(".wig.gz"): # zipped wiggle
            with gzip.open(output_file, 'wt') as out:
                if (verbose):
                    print(f'File opened! Writing...')

                # declaration line
                out.write(
                    f'fixedStep\tchrom=.\tstart={left_of_site}\tstep={1}\tspan'
                    f'={window_size}\n'
                    )
                for score in (tqdm(scores[:, 1])
                              if verbose >= 2
                              else scores[:, 1]):
                    out.write(f'{score}\n')

        elif output_file.endswith(".wig"):  # wiggle
            with open(output_file, 'wt') as out:
                if (verbose):
                    print(f'File opened! Writing...')
                # declaration line
                out.write(
                    f'fixedStep\tchrom=.\tstart={left_of_site}\tstep={1}\tspan'
                    f'={window_size}\n'
                    )
                for score in (tqdm(scores[:, 1])
                              if verbose >= 2
                              else scores[:, 1]):
                    out.write(f'{score}\n')

        else:   # unaccepted file type
            raise ValueError(
                'output_file can only have suffixes .wig or .wig.gz.'
                )

    elif (output_file is not None):
        raise TypeError(
            f'output_file is unsupported type "{type(input_file)}". '
            'output_file should be a string specifying the path of the file '
            'to output scores to.'
            )

    if (verbose):
        end_time = time.time()
        print(f'aggregate_wps took {end_time - start_time} s to complete',
              flush=True)

    return scores


def _single_contig_delfi():
    return None


def delfi(input_bam: Union[str, pysam.AlignmentFile],
          genome_file: str,
          blacklist_file: str,
          window_size: int=5000000,
          subsample_coverage: int=2,
          quality_threshold: int=30,
          workers: int=1,
          preprocessing: bool=True,
          verbose: Union[int, bool]=False):
    """
    A function that replicates the methodology of Christiano et al
    (2019).

    Parameters
    ----------
    input_bam: str or AlignmentFile
        Path string or Alignment File pointing a bam file containing PE
        fragment reads.
    genome_file: str
        Path string to .genome file.
    blacklist_file: str
        Path string to bed file containing genome blacklist.
    window_size: int
        Size of non-overlapping windows to cover genome. Default is
        5 megabases.
    subsample_coverage: int, optional
        The depth at which to subsample the input_bam. Default is 2.
    workers: int, optional
        Number of worker processes to use. Default is 1.
    preprocessing: bool, optional
        Christiano et al (2019)
    verbose: int or bool, optional
        Determines how many print statements and loading bars appear in
        stdout. Default is False.

    """

    # TODO: subsample bam to specified coverage. Jan28.hg19.mdups.bam
    # already has 1-2x coverage.

    if (verbose):
        start_time = time.time()

    with open(genome_file) as genome:
        # read genome file into a list of tuples
        contigs = [(
            line.split()[0],
            int(line.split()[1])
            ) for line in genome.readlines()]

    # generate DELFI windows
    windows = []
    for contig, size in contigs:
        for coordinate in range(0, size, window_size):
            # (contig, start, stop)
            windows.append((contig, coordinate, coordinate + window_size))

    with Pool(workers) as pool:
        pass

    print(contigs)



    if (verbose):
        end_time = time.time()
        print(f'aggregate_wps took {end_time - start_time} s to complete')
    return None


# TODO: look through argparse args and fix them all
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Calculates fragmentation features given a CRAM/BAM/SAM '
        'file',
        epilog='')
    subparsers = parser.add_subparsers(title='subcommands',
                                       dest='subcommand')

    # Common arguments

    # Subcommand 1: frag-coverage
    parser_command1 = subparsers.add_parser('frag-center-coverage',
                                            description=(
                                                'Calculates fragmentation '
                                                'coverage over a region given '
                                                'a CRAM/BAM/SAM file')
                                            )
    parser_command1.add_argument('input_file')
    # inclusive location of region start in 0-based coordinate system.
    # If not included, will end at the end of the chromosome
    parser_command1.add_argument('--start', type=int)
    # exclusive location of region end in 0-based coordinate system.
    # If not included, will end at the end of the chromosome
    parser_command1.add_argument('--stop', type=int)
    parser_command1.add_argument('--region')   # samtools region string
    parser_command1.add_argument('--method', default="frag-center")
    parser_command1.add_argument('-v', '--verbose', default=False, type=bool)
    parser_command1.set_defaults(func=frag_center_coverage)

    # Subcommand 2: frag-length
    parser_command2 = subparsers.add_parser(
        'frag-length', prog='frag-length',
        description='Calculates fragment lengths given a CRAM/BAM/SAM file'
        )
    parser_command2.add_argument('input_file')
    parser_command2.add_argument('--contig')
    parser_command2.add_argument('--output_file')
    parser_command2.add_argument('--workers', default=1, type=int)
    parser_command2.add_argument('--quality_threshold', default=30, type=int)
    parser_command2.add_argument('-v', '--verbose', action='store_true')
    parser_command2.set_defaults(func=frag_length)

    # Subcommand 3: wps()
    parser_command3 = subparsers.add_parser(
        'wps', prog='wps',
        description='Calculates Windowed Protection Score over a region given '
        'a CRAM/BAM/SAM file'
        )
    parser_command3.add_argument('input_file')
    parser_command3.add_argument('contig')
    # inclusive location of region start in 0-based coordinate system.
    # If not included, will start at the beginning of the chromosome
    parser_command3.add_argument('start', type=int)
    # exclusive location of region end in 0-based coordinate system.
    # If not included, will end at the end of the chromosome
    parser_command3.add_argument('stop', type=int)
    parser_command3.add_argument('-o', '--output_file')
    parser_command3.add_argument('--window_size', default=120, type=int)
    parser_command3.add_argument('-lo', '--fraction_low', default=120,
                                 type=int)
    parser_command3.add_argument('-hi', '--fraction_high', default=180,
                                 type=int)
    parser_command3.add_argument('--quality_threshold', default=30, type=int)
    parser_command3.add_argument('-v', '--verbose', action='count')
    parser_command3.set_defaults(func=wps)

    # Subcommand 4: aggregate-wps
    parser_command4 = subparsers.add_parser(
        'aggregate-wps',
        prog='aggregate-wps',
        description='Calculates Windowed Protection Score over a region '
        'around sites specified in a BED file from alignments in a '
        'CRAM/BAM/SAM file'
        )
    parser_command4.add_argument('input_file')
    parser_command4.add_argument('site_bed')
    parser_command4.add_argument('-o', '--output_file')
    parser_command4.add_argument('--size_around_sites', default=5000, type=int)
    parser_command4.add_argument('--window_size', default=120, type=int)
    parser_command4.add_argument('-lo', '--fraction_low', default=120,
                                 type=int)
    parser_command4.add_argument('-hi', '--fraction_high', default=180,
                                 type=int)
    parser_command4.add_argument('--quality_threshold', default=30, type=int)
    parser_command4.add_argument('--workers', default=1, type=int)
    parser_command4.add_argument('-v', '--verbose', action='count')
    parser_command4.set_defaults(func=aggregate_wps)


    args = parser.parse_args()
    function = args.func
    funcargs = vars(args)
    funcargs.pop('func')
    funcargs.pop('subcommand')
    # print(funcargs)
    function(**funcargs)
