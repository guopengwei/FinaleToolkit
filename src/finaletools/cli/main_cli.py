#!/usr/bin/env python3

from __future__ import annotations
import argparse

from finaletools.frag.frag_length import (
    frag_length, frag_length_bins, frag_length_intervals
)
from finaletools.utils.filter_bam import filter_bam
from finaletools.frag.coverage import coverage
from finaletools.frag.multi_wps import multi_wps
from finaletools.frag.delfi import delfi
from finaletools.frag.process_wps import process_wps


# TODO: implement subcommands read from stdin
# TODO: implement pipelining
def main_cli():
    parser = argparse.ArgumentParser(
        description='Calculates fragmentation features given a CRAM/BAM/SAM '
        'file',
        epilog='')
    subparsers = parser.add_subparsers(title='subcommands',
                                       dest='subcommand')

    # Common arguments

    # Subcommand 1: frag-coverage
    parser_command1 = subparsers.add_parser(
        'coverage',
        description=(
        'Calculates fragmentation coverage over intervals in a BED file given '
        'a BAM/SAM file'
        )
    )
    # TODO: accept tabix

    parser_command1.add_argument(
        'input_file',
        help='BAM or SAM file containing fragment data'
    )
    parser_command1.add_argument(
        'interval_file',
        help='BED file containing intervals over which coverage is calculated'
    )
    parser_command1.add_argument(
        '-o',
        '--output_file',
        default='-',
        help='BED file where coverage is printed'
    )
    parser_command1.add_argument(
        '-s',
        '--scale-factor',
        default=1e6,
        type=float,
        help='Amount coverage will be multiplied by'
    )
    parser_command1.add_argument(
        '-q',
        '--quality_threshold',
        default=30,
        type=int
    )
    parser_command1.add_argument(
        '-w',
        '--workers',
        default=1,
        type=int,
        help='Number of worker processes to use. Default is 1.'
    )
    parser_command1.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        default=0
    )
    parser_command1.set_defaults(func=coverage)

    # Subcommand 2: frag-length
    parser_command2 = subparsers.add_parser(
        'frag-length', prog='finaletools-frag-length',
        description='Calculates fragment lengths given a CRAM/BAM/SAM file'
        )
    parser_command2.add_argument('input_file')
    parser_command2.add_argument('-c', '--contig')
    parser_command2.add_argument('-o', '--output_file')
    parser_command2.add_argument('-w', '--workers', default=1, type=int)
    parser_command2.add_argument('-q', '--quality_threshold', default=30, type=int)
    parser_command2.add_argument('-v', '--verbose', action='count', default=0)
    parser_command2.set_defaults(func=frag_length)

    # Subcommand 3: frag_length_bins()
    parser_command3 = subparsers.add_parser(
        'frag-length-bins', prog='finaletools-frag-length-bins',
        description='computes frag lengths of fragments and either prints'
        'bins and counts to tsv or prints a histogram'
        )
    parser_command3.add_argument('input_file')
    parser_command3.add_argument('--contig')
    parser_command3.add_argument('--start', type=int)
    parser_command3.add_argument('--stop', type=int)
    parser_command3.add_argument('--bin-size', type=int)
    parser_command3.add_argument('-o', '--output-file')
    parser_command3.add_argument('--contig-by-contig', action='store_true')
    parser_command3.add_argument('--histogram', action='store_true')
    parser_command3.add_argument('--quality-threshold', default=30, type=int)
    parser_command3.add_argument('-v', '--verbose', action='count', default=0)
    parser_command3.set_defaults(func=frag_length_bins)

    # Subcommand 3_1: frag_length_intervals
    parser_command3_1 = subparsers.add_parser(
        'frag-length-intervals',
        description='Calculates frag lengths statistics for intervals'
    )
    parser_command3_1.add_argument(
        'input_file',
        help='BAM or SAM file containing PE WGS of cfDNA'
    )
    parser_command3_1.add_argument(
        'interval_file',
        help='BED file containing intervals over which to produce statistics'
    )
    parser_command3_1.add_argument(
        '-o',
        '--output-file',
        default='-',
        help='File to print results to. if "-", will print to stdout. Default'
        'is "-".'
    )
    parser_command3_1.add_argument(
        '-q',
        '--quality-threshold',
        default=30,
        type=int,
        help='minimum MAPQ to filter for'
    )
    parser_command3_1.add_argument(
        '-w',
        '--workers',
        default=1,
        type=int,
        help='Number of subprocesses to use'
    )
    parser_command3_1.add_argument(
        '-v',
        '--verbose',
        default=0,
        action='count',
        help='Determines how much is written to stderr'
    )
    parser_command3_1.set_defaults(func=frag_length_intervals)

    # Subcommand 4: wps (on interval bed file)
    parser_command4 = subparsers.add_parser(
        'wps',
        prog='finaletools-wps',
        description='Calculates Windowed Protection Score over a region '
        'around sites specified in a BED file from alignments in a '
        'CRAM/BAM/SAM file'
    )
    parser_command4.add_argument(
        'input_file',
        help='bam or sam file containing paired-end reads of cfDNA WGS'
    )
    parser_command4.add_argument(
        'site_bed',
        help='bed file containing sites over which to calculate wps'
    )
    parser_command4.add_argument(
        '-o',
        '--output_file',
        default='-'
    )
    parser_command4.add_argument(
        '-i',
        '--interval_size',
        default=5000,
        type=int
    )
    parser_command4.add_argument(
        '-W',
        '--window_size',
        default=120,
        type=int
    )
    parser_command4.add_argument(
        '-lo',
        '--fraction_low',
        default=120,
        type=int
    )
    parser_command4.add_argument(
        '-hi',
        '--fraction_high',
        default=180,
        type=int
    )
    parser_command4.add_argument(
        '-q',
        '--quality_threshold',
        default=30,
        type=int
    )
    parser_command4.add_argument(
        '-w',
        '--workers',
        default=1,
        type=int
    )
    parser_command4.add_argument(
        '-v',
        '--verbose',
        action='count',
        default=0)
    parser_command4.set_defaults(func=multi_wps)

    # Subcommand 5: delfi
    parser_command5 = subparsers.add_parser(
        'delfi',
        prog='finaletools-delfi',
        description='Calculates DELFI score over genome'
        )
    parser_command5.add_argument('input_file')
    parser_command5.add_argument('autosomes')
    parser_command5.add_argument('reference_file')
    parser_command5.add_argument('-b', '--blacklist_file')
    parser_command5.add_argument('-c', '--centromere_file')
    parser_command5.add_argument('-o', '--output_file')
    parser_command5.add_argument('-W', '--window_size', default=100000, type=int)
    parser_command5.add_argument('-q', '--quality_threshold', default=30, type=int)
    parser_command5.add_argument('-gc', '--gc_correction', action='store_true')
    parser_command5.add_argument('-w', '--workers', default=1, type=int)
    parser_command5.add_argument('-v', '--verbose', action='count', default=0)
    parser_command5.set_defaults(func=delfi)

    # Subcommand 6: filter_bam
    parser_command6 = subparsers.add_parser(
        'filter-bam',
        prog='finaletools-filter-bam',
        description='Filters a BAM file so that all reads are in mapped pairs'
        ', exceed a certain MAPQ, are not flagged for quality, are read1, are'
        ' not secondary or supplementary alignments, and are on the same'
        'reference sequence as the mate.'
    )
    parser_command6.add_argument(
        'input_file',
        help='BAM file with PE WGS'
    )
    parser_command6.add_argument(
        '-r',
        '--region-file',
        default=None,
        help='BED file containing regions to read fragments from. Default is'
        ' None.'
    )
    parser_command6.add_argument(
        '-o',
        '--output-file',
        default='-',
        help='Path to write filtered BAM. Defualt is "_". If set to "_",'
        ' the BAM file will be written to stdout.'
    )
    parser_command6.add_argument(
        '-q',
        '--quality_threshold',
        type=int,
        default=30,
        help='Minimum mapping quality to filter for. Defualt is 30.'
    )
    parser_command6.add_argument(
        '-hi',
        '--fraction-high',
        type=int,
        default=None,
        help='Maximum fragment size. Default is None'
    )
    parser_command6.add_argument(
        '-lo',
        '--fraction-low',
        type=int,
        default=None,
        help='Minimum fragment size. Default is None'
    )
    parser_command6.add_argument(
        '-w',
        '--workers',
        type=int,
        default=1,
        help='Number of worker processes to spawn.'
    )
    parser_command6.add_argument(
        '-v',
        '--verbose',
        action='count',
        help='Specify verbosity. Number of printed statements is proportional to number of vs.'
    )
    parser_command6.set_defaults(func=filter_bam)

    # Subcommand 7: process WPS
    parser_command7 = subparsers.add_parser(
        'process-wps',
        prog='finaletools-process-wps',
        description='Reads WPS data from a WIG file and applies a median filter'
        ' and a Savitsky-Golay filter (Savitsky and Golay, 1964).'
    )
    parser_command7.add_argument(
        'input_file',
        help='WIG file with WPS data. If "-", will read from stdin.'
    )
    parser_command7.add_argument(
        '-o',
        '--output-file',
        default='-',
        help='WIG file to print filtered WPS data. If "-", will write to '
        'stdout. Default is "-".'
    )
    parser_command7.add_argument(
        '-m',
        '--larm-window-size',
        default=1000,
        type=int,
        help='Size of window for median filter. Default is 1000.'
    )
    parser_command7.add_argument(
        '-s',
        '--savgol-window-size',
        default=21,
        type=int,
        help='Size of window for Savitsky-Golay filter. Default is 21.'
    )
    parser_command7.add_argument(
        '-p',
        '--savgol-poly-deg',
        default=2,
        type=int,
        help='Degree polynomial for Savitsky-Golay filter. Default is 1000.'
    )
    parser_command7.set_defaults(func=process_wps)

    args = parser.parse_args()
    function = args.func
    funcargs = vars(args)
    funcargs.pop('func')
    funcargs.pop('subcommand')

    function(**funcargs)

if __name__ == '__main__':
    main_cli()
