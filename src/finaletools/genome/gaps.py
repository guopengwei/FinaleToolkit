"""
FinaleTools.gaps
================

This module contains classes and functions to use the gap tracks found
on the UCSC Genome Browser (Kent et al 2002).
"""

from __future__ import annotations
from typing import Union, Tuple, Iterable
import gzip
try:
    from importlib.resources import files
except ImportError:
    from importlib_resources import files
from pathlib import Path
from sys import stdout

import numpy as np
from numpy.typing import NDArray

import finaletools.genome as genome

HG19GAPS: Path = (files(genome) / 'data' / 'hg19.gap.txt.gz')
HG38GAPS: Path = (files(genome) / 'data' / 'hg19.gap.txt.gz')
HG38CENTROMERES: Path = (files(genome) / 'data' / 'hg38.centromeres.txt.gz')


class GenomeGaps:
    """
    Reads telomere, centromere, and short_arm intervals from a bed file
    or generates these intervals from UCSC gap and centromere tracks for
    hg19 and hg38.
    """
    def __init__(self, gaps_bed: Union[Path, str]=None):
        self.centromeres: NDArray
        self.telomeres: NDArray
        self.short_arms: NDArray
        if gaps_bed is None:
            pass
        else:
            gaps = np.genfromtxt(
                gaps_bed,
                dtype=[
                    ('contig', '<U32'),
                    ('start', '<i8'),
                    ('stop', '<i8'),
                    ('type', '<U32'),
                ]
            )
            self.centromeres = gaps[gaps['type'] == 'centromere']
            self.telomeres = gaps[gaps['type'] == 'telomere']
            self.short_arms = gaps[gaps['type'] == 'short_arm']

    @classmethod
    def ucsc_hg19(cls):
        """
        Creates a GenomeGaps for the UCSC hg19 reference genome. This
        sequences uses chromosome names that start with 'chr' and is
        based on a version of the GRCh37 reference genome.

        Returns
        -------
        gaps : GenomeGaps
            GenomeGaps for the UCSC hg19 reference genome.
        """
        genome_gaps = cls()
        gaps = np.genfromtxt(
            HG19GAPS,
            usecols=[1, 2, 3, 7],
            dtype=[
                ('contig', '<U32'),
                ('start', '<i8'),
                ('stop', '<i8'),
                ('type', '<U32'),
            ]
        )
        genome_gaps.centromeres = gaps[gaps['type'] == 'centromere']
        genome_gaps.telomeres = gaps[gaps['type'] == 'telomere']
        genome_gaps.short_arms = gaps[gaps['type'] == 'short_arm']

        return genome_gaps

    @classmethod
    def b37(cls):
        """
        Creates a GenomeGaps for the Broad Institute GRCh37 reference
        genome i.e b37. This reference genome is also based on GRCh37,
        but differs from the UCSC hg19 reference in a few ways,
        including the absence of the 'chr' prefix. We generate this
        GenomeGap using an ad hoc method where we take the UCSC hg19
        gap track and drop 'chr' from the chromosome names. Because
        there are other differences between hg19 and b37, this is not
        a perfect solution.

        Returns
        -------
        gaps : GenomeGaps
            GenomeGaps for the b37 reference genome.
        """
        genome_gaps = cls()
        gaps = np.genfromtxt(
            HG19GAPS,
            usecols=[1, 2, 3, 7],
            dtype=[
                ('contig', '<U32'),
                ('start', '<i8'),
                ('stop', '<i8'),
                ('type', '<U32'),
            ]
        )
        gaps['contig'] = np.char.replace(gaps['contig'], 'chr', '')
        genome_gaps.centromeres = gaps[gaps['type'] == 'centromere']
        genome_gaps.telomeres = gaps[gaps['type'] == 'telomere']
        genome_gaps.short_arms = gaps[gaps['type'] == 'short_arm']

        return genome_gaps

    @classmethod
    def ucsc_hg38(cls):
        return NotImplemented

    def in_tcmere(self, contig: str, start: int, stop: int) -> bool:
        """
        Checks if specified interval is in a centromere or telomere

        Parameters
        ----------
        contig : str
            Chromosome name
        start : int
            Start of interval
        stop : int
            End of interval

        Returns
        -------
        in_telomere_or_centromere : bool
            True if in a centromere or telomere
        """
        # get centromere and telomeres for contig
        centromere = self.centromeres[self.centromeres['contig'] == contig]
        telomeres = self.telomeres[self.telomeres['contig'] == contig]
        if not (centromere.shape[0] or telomeres.shape[0]):
            return None
        else:
            in_centromere = np.logical_and(
                stop > centromere['start'],
                start < centromere['stop'],
            )
            in_telomeres = np.sum(np.logical_and(
                stop > telomeres['start'],
                start < telomeres['stop'],
            )) > 0
            return in_centromere or in_telomeres

    def get_arm(self, contig: str, start: int, stop: int) -> str:
        """
        Returns the chromosome arm the interval is in. If in
        the short arm of an acrocentric chromosome or intersects a
        centromere, returns an empty string.

        contig : str
            Chromosome of interval.
        start : int
            Start of interval.
        stop : int
            End of interval.

        Returns
        -------
        arm : str
            Arm that interval is in.

        Raises
        ------
        ValueError
            Raised for invalid coordinates
        """
        if stop < start:
            raise ValueError('start must be less than stop')

        # get centromere and short_arm for contig
        centromere = self.centromeres[self.centromeres['contig'] == contig]
        short_arm = self.short_arms[self.short_arms['contig'] == contig]
        has_short_arm = short_arm.shape[0] > 0
        if stop < centromere['start'][0]:
            if not has_short_arm:
                return f"p{contig.replace('chr', '')}"
            else:
                return ''
        elif start > centromere['stop'][0]:
            return f"q{contig.replace('chr', '')}"
        else:
            return ''

    def get_contig_gaps(self, contig):
        # get centromere and telomeres for contig
        centromere = self.centromeres[self.centromeres['contig'] == contig]
        centromere_ends = (centromere[0]['start'], centromere[0]['stop'])
        telomeres = self.telomeres[self.telomeres['contig'] == contig]
        telomere_ends = [
            (telomeres[0]['start'], telomeres[0]['stop']),
            (telomeres[1]['start'], telomeres[1]['stop']),
        ]
        # get short_arm for contig
        short_arm = self.short_arms[self.short_arms['contig'] == contig]
        has_short_arm = short_arm.shape[0] > 0
        contig_gaps = ContigGaps(
            contig, centromere_ends, telomere_ends, has_short_arm
        )
        return contig_gaps

    def to_bed(self, output_file: str):
        """
        Prints gap intervals in GenomeGaps to a BED4 file where the name
        is the type of gap interval.

        Parameters
        ----------
        output_file : str
            File to write to. Optionally gzipped. If output_file == '-',
            results will be writted to stdout.
        """
        gaps = np.sort(np.append(np.append(self.centromeres, self.telomeres), self.short_arms))
        if output_file.endswith('.gz'):
            with gzip.open(output_file, 'w') as output:
                for interval in gaps:
                    output.write(
                        f"{interval['contig']}\t{interval['start']}\t"
                        f"{interval['stop']}\t{interval['type']}\n"
                    )
        elif output_file == '-':
            for interval in gaps:
                    stdout.write(
                        f"{interval['contig']}\t{interval['start']}\t"
                        f"{interval['stop']}\t{interval['type']}\n"
                    )
        else:
            with open(output_file, 'w') as output:
                for interval in gaps:
                    output.write(
                        f"{interval['contig']}\t{interval['start']}\t"
                        f"{interval['stop']}\t{interval['type']}\n"
                    )


class ContigGaps():
    def __init__(self,
                 contig: str,
                 centromere: Tuple[int, int],
                 telomeres:Iterable[Tuple[int, int]],
                 has_short_arm: bool=False):
        self.contig = contig
        self.centromere = centromere
        self.telomeres = telomeres
        self.has_short_arm = has_short_arm

    def in_tcmere(self, start: int, stop: int):
        in_centromere = (
            stop > self.centromere[0] and start < self.centromere[1]
        )
        in_telomeres = all(
            stop > telomere[0] and start < telomere[1]
            for telomere in self.telomeres
        )
        return in_centromere or in_telomeres

    def get_arm(self, start: int, stop: int):
        if stop < start:
            raise ValueError('start must be less than stop')

        if stop < self.centromere[0]:
            if not self.has_short_arm:
                return f"p{self.contig.replace('chr', '')}"
            else:
                return ''
        elif start > self.centromere[1]:
            return f"q{self.contig.replace('chr', '')}"
        else:
            return ''


def ucsc_hg19_gap_bed(output_file: str):
    """
    Creates BED4 of centromeres, telomeres, and short arms for the UCSC
    hg19 reference sequence.

    Parameters
    ----------
    output_file : str
        Output path
    """
    return GenomeGaps.ucsc_hg19().to_bed(output_file)


def b37_gap_bed(output_file: str):
    """
    Creates BED4 of centromeres, telomeres, and short arms for the Broad
    Institute GRCh37 (b37) reference sequence. Also useful for
    files aligned to human_g1k_v37 (1000 Genomes Project).

    Parameters
    ----------
    output_file : str
        Output path
    """
    return GenomeGaps.b37().to_bed(output_file)


def ucsc_hg38_gap_bed(output_file: str):
    """
    Creates BED4 of centromeres, telomeres, and short arms for the UCSC
    hg38 reference sequence.

    Parameters
    ----------
    output_file : str
        Output path
    """
    return NotImplemented