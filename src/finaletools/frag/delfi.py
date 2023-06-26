from __future__ import annotations
import time
import sys
from multiprocessing.pool import Pool
from typing import Union

import pysam
import numpy as np
from numba import jit
from tqdm import tqdm
from finaletools.utils import not_read1_or_low_quality


def _delfi_single_window(
        input_file: str,
        contig: str,
        window_start: int,
        window_stop: int,
        blacklist_file: str=None,
        quality_threshold: int=30,
        verbose: Union[int,bool]=False) -> tuple:
    """
    Calculates DELFI for one window.
    """
    blacklist_regions = []

    if (blacklist_file is not None):


        # convert blacklist to a list of tuples
        # TODO: accept other file types
        with open(blacklist_file) as blacklist:
            for line in blacklist:
                region_contig, region_start, region_stop, *_ = line.split()
                region_start = int(region_start)
                region_stop = int(region_stop)
                if (contig == region_contig
                    and window_start <= region_start
                    and window_stop >= region_stop ):
                    blacklist_regions.append((region_start,region_stop))

    small_lengths = []
    large_lengths = []
    gc_tally = 0  # cumulative sum of gc bases
    base_tally = 0


    with pysam.AlignmentFile(input_file) as sam_file:
        # Iterating on each read in file in specified contig/chromosome
        for read1 in (sam_file.fetch(contig=contig,
                                        start=window_start,
                                        stop=window_stop)):
            # Only select forward strand and filter out non-paired-end
            # reads and low-quality reads
            if (not_read1_or_low_quality(read1, quality_threshold)):
                pass
            else:
                frag_start = read1.reference_start
                frag_length = read1.reference_length
                frag_end = frag_start + frag_length

                # check if in blacklist
                blacklisted = False
                for region in blacklist_regions:
                    if (
                        (frag_start >= region[0] and frag_start < region[1])
                        or (frag_end >= region[0] and frag_end < region[1])
                    ):
                        blacklisted = True
                        break


                if (not blacklisted
                    and frag_length >= 100
                    and frag_length <= 220
                ):
                    # append length of fragment to list
                    if (frag_length >= 151):
                        large_lengths.append(abs(frag_length))
                    else:
                        small_lengths.append(abs(frag_length))

                    # tally gc content
                    try:
                        sequence = read1.get_reference_sequence()
                        gc_tally += sum([base.upper() == 'G'
                                        or base.upper() == 'C'
                                        for base
                                        in sequence])
                        base_tally += frag_length
                    except ValueError as e:
                        print(e)
                        exit(1)

                    except Exception as e:
                        print(e)

    gc_content = gc_tally / base_tally if base_tally != 0 else np.NaN

    if (len(small_lengths) != 0 or len(large_lengths) != 0):
        print(len(small_lengths), len(large_lengths), gc_content)

    return small_lengths, large_lengths, gc_tally


def delfi(input_file: str,  # TODO: allow AlignmentFile to be used
          genome_file: str,
          blacklist_file: str=None,
          window_size: int=100000,
          subsample_coverage: float=2,
          quality_threshold: int=30,
          workers: int=1,
          preprocessing: bool=True,
          verbose: Union[int, bool]=False):
    """
    A function that replicates the methodology of Christiano et al
    (2019).

    Parameters
    ----------
    input_file: str
        Path string pointing to a bam file containing PE
        fragment reads.
    genome_file: str
        Path string to .genome file. Should contain only autosomal chromosomes
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

    if verbose:
        print(f'Reading genome file...')

    contigs = []
    with open(genome_file) as genome:
        for line in genome:
            contents = line.split('\t')
            # account for empty lines
            if len(contents) > 1:
                contigs.append((contents[0],  int(contents[1])))

    if verbose:
        print(f'Generating windows')

    # generate DELFI windows
    window_args = []
    for contig, size in contigs:
        for coordinate in range(0, size, window_size):
            # (contig, start, stop)
            window_args.append((input_file,
                            contig,
                            coordinate,
                            coordinate + window_size,
                            blacklist_file,
                            quality_threshold))

    if (verbose):
        print(f'{len(window_args)} windows created.')
        print('Calculating fragment lengths...')

    with Pool(workers) as pool:
        windows = pool.starmap(_delfi_single_window, window_args)

    if (verbose):
        end_time = time.time()
        print(f'delfi took {end_time - start_time} s to complete')
    return None
