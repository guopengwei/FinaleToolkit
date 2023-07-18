from __future__ import annotations
from typing import Union, Iterable
from multiprocessing import Pool
from time import time
from sys import stderr
try:
    from importlib.resources import files
except ImportError:
    from importlib_resources import files
from pathlib import PosixPath

import tqdm
import py2bit
import numpy as np
from numpy.typing import NDArray

from finaletools.utils.utils import frag_generator
import finaletools.frag as pkg_data

# path to tsv containing f-profiles from Zhou et al (2023)
FPROFILE_PATH: PosixPath = (files(pkg_data) / 'data' / 'end_motif_f_profiles.tsv')


class EndMotifFreqs(dict):
    """
    Class that stores frequencies of end-motif k-mer frequencies and
    contains methods to manipulate this data. Can also be indexed like
    a Python dictionary to return frequencies.

    Parameters
    ----------
    kmer_frequencies : Iterable
        A Iterable of tuples, each containing a str representing a k-mer
        and a float representing its frequency
    k : int
        Size of k-mers
    refseq_file: str
        A 2bit file containing the reference sequence that cfDNA
        fragments were aligned to
    quality_threshold: int, optional
        Minimum mapping quality used. Default is 30.

    """

    def __init__(
        self,
        kmer_frequencies: Iterable,
        k: int,
        refseq_file: str,
        quality_threshold: int = 30,
    ):
        super().__init__(kmer_frequencies)
        self.k = k
        self.refseq_file = refseq_file
        self.quality_threshold = quality_threshold
        if not all(len(kmer) == k for kmer, _ in kmer_frequencies):
            raise ValueError(
                'kmer_frequencies contains a kmer with length not equal'
                ' to k.'
            )


def _gen_kmers(k: int, bases: str) -> list:
        """Function to recursively create a list of k-mers."""
        if k == 1:
            return [base for base in bases]
        else:
            kmers = []
            for k_minus_mer in _gen_kmers(k-1, bases):
                for base in bases:
                    kmers.append(k_minus_mer+base)
            return kmers


def _reverse_complement(kmer: str) -> str:
    reversed = kmer[-1::-1]
    pair_dict = {'A': 'T',
                 'T': 'A',
                 'G': 'C',
                 'C': 'G'}
    complemented = ''.join(pair_dict[base] for base in reversed)
    return complemented


def region_end_motifs(
    input_file: str,
    contig: str,
    start: int,
    stop: int,
    refseq_file: str,
    k: int = 4,
    output_file: Union(None, str) = None,
    quality_threshold: int = 30,
    verbose: Union(bool, int) = False,
) -> dict:
    """
    Function that reads fragments in the specified region from a BAM,
    SAM, or tabix indexed file and returns the 5' k-mer (default is
    4-mer) end motif counts as a structured array. This function
    reproduces the methodology of Zhou et al (2023).

    Parameters
    ----------
    input_file : str
    contig : str
    start : int
    stop : int
    refseq_file : str
    k : int, optional
    output_file : None or str, optional
    quality_threshold : int, optional
    verbose : bool or int, optional

    Return
    ------
    end_motif_freq : dict
    """
    if verbose:
        start_time = time()

    # numpy array of fragments
    frag_ends = frag_generator(
        input_file,
        contig,
        quality_threshold,
        start,
        stop,
        fraction_low=4,
        fraction_high=100000,
    )
    # create dict where keys are kmers and values are counts
    bases='ACGT'
    kmer_list = _gen_kmers(k, bases)
    end_motif_counts = dict(zip(kmer_list, 4**k*[0]))

    # TODO: accept other reference file types e.g. FASTA
    # count end motifs
    try:
        refseq = py2bit.open(refseq_file, 'r')
        for frag in frag_ends:
            # forward end-motif
            forward_kmer = refseq.sequence(
                contig, int(frag[1]), int(frag[1]+k)
            )
            if 'N' not in forward_kmer:
                end_motif_counts[forward_kmer] += 1

            # reverse end-motif
            reverse_kmer = refseq.sequence(
                contig, int(frag[2]-k), int(frag[2])
            )
            if 'N' not in reverse_kmer:
                end_motif_counts[_reverse_complement(reverse_kmer)] += 1
    finally:
        refseq.close()

    if verbose:
        stop_time = time()
        stderr.write(
            f'region_end_motifs took {stop_time-start_time} seconds to run\n'
        )

    return end_motif_counts


def _region_end_motifs_star(args) -> NDArray:
    results_dict = region_end_motifs(*args)
    return np.array(list(results_dict.values()), dtype='<f8')


def end_motifs(
    input_file: str,
    refseq_file: str,
    k: int = 4,
    output_file: Union(None, str) = None,
    quality_threshold: int = 30,
    workers: int = 1,
    verbose: Union(bool, int) = False,
) -> EndMotifFreqs:
    """
    Function that reads fragments from a BAM, SAM, or tabix indexed
    file and returns the 5' k-mer (default is 4-mer) end motif
    frequencies as a dictionary. Optionally writes data to a tsv. This
    function reproduces the methodology of Zhou et al (2023).

    Parameters
    ----------
    input_file : str
    refseq_file : str
    k : int, optional
    output_file : None or str, optional
    quality_threshold : int, optional
    workers : int, optional
    verbose : bool or int, optional

    Return
    ------
    end_motif_freq : list
    """
    if verbose:
        start_time = time()

    bases='ACGT'
    kmer_list = _gen_kmers(k, bases)

    # read chromosomes from py2bit
    try:
        refseq = py2bit.open(refseq_file, 'r')
        chroms: dict = refseq.chroms()
    finally:
        refseq.close()

    # generate list of inputs
    intervals = []
    window_size = 1000000
    for chrom, chrom_length in chroms.items():
        for start in range(0, chrom_length, window_size):
            intervals.append((
                input_file,
                chrom,
                start,
                start+window_size,
                refseq_file,
                k,
                None,
                quality_threshold,
                verbose - 2 if verbose > 2 else 0
            ))
        intervals.append((
            input_file,
            chrom,
            chrom_length - chrom_length%window_size,
            chrom_length,
            refseq_file,
            k,
            None,
            quality_threshold,
            verbose - 2 if verbose > 2 else 0
        ))

    # use process pool to count kmers
    try:
        # open pool
        pool = Pool(workers)

        # uses tqdm loading bar if verbose == True
        counts_iter = pool.imap(
            _region_end_motifs_star,
            tqdm.tqdm(intervals, 'Reading 1mb windows', position=0)if verbose else intervals,
            chunksize=min(int(len(intervals)/workers/2+1), 1000)
        )

        ccounts = np.zeros((4**k,), np.float64)
        for count in tqdm.tqdm(counts_iter, 'Counting end-motifs', len(intervals), position=1) if verbose else counts_iter:
            ccounts = ccounts + count

    finally:
        pool.close()

    frequencies = ccounts/np.sum(ccounts)

    results = EndMotifFreqs(
        zip(kmer_list, frequencies),
        k,
        refseq_file,
        quality_threshold
    )

    # FIXME: output to file
    if verbose:
        stop_time = time()
        tqdm.tqdm.write(
            f'end_motifs took {stop_time-start_time} seconds to run\n'
        )

    return results