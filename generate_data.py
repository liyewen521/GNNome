import argparse
import os
import re
import subprocess

from Bio import SeqIO, AlignIO

import graph_dataset
import train_valid_chrs
from configs.config import get_config


class InvalidSuffixError(Exception):
    def __init__(self):
        self.message = f'Invalid suffix of chromosomes in train_valid_chromosome.py script. Currently only "_hg002" is supported: e.g. "chr6_hg002".'
        super().__init__(self.message)


class SampleProfileUnspecifiedError(Exception):
    def __init__(self):
        self.message = f'Sample profile ID for PBSIM3 is unspecified. Provide a value for it in config.py script.'
        super().__init__(self.message)


def change_description_seqreq(file_path):
    new_fasta = []
    for record in SeqIO.parse(file_path, file_path[-5:]):  # 'fasta' for FASTA file, 'fastq' for FASTQ file
        des = record.description.split(",")
        id = des[0][5:]
        if des[1] == "forward":
            strand = '+'
        else:
            strand = '-'
        position = des[2][9:].split("-")
        start = position[0]
        end = position[1]
        record.id = id
        record.description = f'strand={strand} start={start} end={end}'
        new_fasta.append(record)
    SeqIO.write(new_fasta, file_path, "fasta")


def change_description_pbsim(fastq_path, maf_path, chr):
    chr = int(chr[3:])
    reads = {r.id: r for r in SeqIO.parse(fastq_path, 'fastq')}
    for align in AlignIO.parse(maf_path, 'maf'):
        ref, read_m = align
        # .annotations['size'] gives a correct length of the sequence
        # len(ref.seq) can give wrong length because '-' characters can be include in the sequence (since MAF is for MSA)
        start = ref.annotations['start']  # Lower-bound included
        end = start + ref.annotations['size']  # Upper-bound excluded --> read == ref[start:end] --> Pythonic!
        strand = '+' if read_m.annotations['strand'] == 1 else '-'
        description = f'strand={strand} start={start} end={end} chr={chr}'
        reads[read_m.id].id += f'_chr{chr}'
        reads[read_m.id].name += f'_chr{chr}'
        reads[read_m.id].description = description
    fasta_path = fastq_path[:-1] + 'a'
    SeqIO.write(list(reads.values()), fasta_path, 'fasta-2line')
    os.remove(fastq_path)
    return fasta_path


def merge_dicts(d1, d2, d3={}):
    keys = {*d1, *d2, *d3}
    merged = {key: d1.get(key, 0) + d2.get(key, 0) + d3.get(key, 0) for key in keys}
    return merged


def handle_pbsim_output(idx, chrN, chr_raw_path, combo=False):
    if combo == True:
        idx = chrN
    subprocess.run(f'mv {idx}_0001.fastq {idx}.fastq', shell=True, cwd=chr_raw_path)
    subprocess.run(f'mv {idx}_0001.maf {idx}.maf', shell=True, cwd=chr_raw_path)
    subprocess.run(f'rm {idx}_0001.ref', shell=True, cwd=chr_raw_path)
    fastq_path = os.path.join(chr_raw_path, f'{idx}.fastq')
    maf_path = os.path.join(chr_raw_path, f'{idx}.maf')
    print(f'Adding positions for training...')
    fasta_path = change_description_pbsim(fastq_path, maf_path, chr=chrN)  # Extract positional info from the MAF file
    print(f'Removing the MAF file...')
    subprocess.run(f'rm {idx}.maf', shell=True, cwd=chr_raw_path)
    if combo:
        return fasta_path
    else:
        return None


# 1. Simulate the sequences - HiFi
def simulate_reads_hifi(datadir_path, chrs_path, chr_dict, assembler, pbsim3_dir, sample_profile_id, sample_file_path, depth):
    print(f'SETUP - simulate')
    datadir_path = os.path.abspath(datadir_path)
    chrs_path = os.path.abspath(chrs_path)
    for chrN_flag, n_need in chr_dict.items():
        if chrN_flag.endswith('_r'):
            continue
        if '+' in chrN_flag:
            continue
        elif chrN_flag.endswith('_hg002'):
            chrN = chrN_flag[:-6]
            chr_seq_path = os.path.join(chrs_path, f'{chrN}.fasta')
        else:
            raise InvalidSuffixError

        chr_raw_path = os.path.join(datadir_path, f'{chrN}/raw')
        chr_processed_path = os.path.join(datadir_path, f'{chrN}/{assembler}/processed')
        if not os.path.isdir(chr_raw_path):
            os.makedirs(chr_raw_path)
        if not os.path.isdir(chr_processed_path):
            os.makedirs(chr_processed_path)

        # TODO: Fix so that you can delete raw files
        raw_files = {int(re.findall(r'(\d+).fast*', raw)[0]) for raw in os.listdir(chr_raw_path)}
        prc_files = {int(re.findall(r'(\d+).dgl', prc)[0]) for prc in os.listdir(chr_processed_path)}
        all_files = raw_files | prc_files
        n_have = max(all_files) + 1 if all_files else 0

        if n_need <= n_have:
            continue
        n_diff = n_need - n_have
        print(f'SETUP - simulate: Simulate {n_diff} datasets for {chrN_flag} with PBSIM3')
        for i in range(n_diff):
            idx = n_have + i
            chr_save_path = os.path.join(chr_raw_path, f'{idx}.fasta')
            print(f'\nStep {i}: Simulating reads {chr_save_path}')
            # Use the CHM13/HG002 profile for all the chromosomes
            if len(sample_profile_id) == 0:
                raise SampleProfileUnspecifiedError
            if f'sample_profile_{sample_profile_id}.fastq' not in os.listdir(pbsim3_dir):
                assert os.path.isfile(sample_file_path), "Sample profile ID and sample file not found! Provide either a valid sample profile ID or a sample file."
                subprocess.run(f'./src/pbsim --strategy wgs --method sample --depth {depth} --genome {chr_seq_path} ' \
                                f'--sample {sample_file_path} '
                                f'--sample-profile-id {sample_profile_id} --prefix {chr_raw_path}/{idx}', shell=True, cwd=pbsim3_dir)
            else:
                subprocess.run(f'./src/pbsim --strategy wgs --method sample --depth {depth} --genome {chr_seq_path} ' \
                                f'--sample-profile-id {sample_profile_id} --prefix {chr_raw_path}/{idx}', shell=True, cwd=pbsim3_dir)
            handle_pbsim_output(idx, chrN, chr_raw_path)


# 2. Generate the graphs
def generate_graphs_hifi(datadir_path, chr_dict, assembler, threads):
    print(f'SETUP - generate')
    datadir_path = os.path.abspath(datadir_path)
    for chrN_flag, n_need in chr_dict.items():
        if chrN_flag.endswith('_hg002'):
            chrN = chrN_flag[:-6]
            chr_sim_path = os.path.join(datadir_path, f'{chrN}')
        else:
            raise InvalidSuffixError
        chr_prc_path = os.path.join(chr_sim_path, f'{assembler}/processed')
        n_prc = len(os.listdir(chr_prc_path))
        if n_need < n_prc:
            continue
        n_diff = max(0, n_need - n_prc)
        if n_diff > 0:
            print(f'SETUP - generate: Generate {n_diff} graphs for {chrN}')
            graph_dataset.AssemblyGraphDataset_HiFi(chr_sim_path, assembler=assembler, threads=threads, generate=True, n_need=n_need)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--datadir', type=str, help='path to directory where the generated data will be saved')
    parser.add_argument('--chrdir', type=str, help='path to directory where the chromosome references are stored')
    parser.add_argument('--asm', type=str, help='assembler used for the assembly graph construction [hifiasm|raven]')
    parser.add_argument('--threads', type=int, default=1, help='number of threads used for running the assembler')
    args = parser.parse_args()

    chrs_path = args.chrdir
    assembler = args.asm
    datadir_path = args.datadir
    threads = args.threads

    config = get_config()
    pbsim3_dir = config['pbsim3_dir']
    sample_profile_id = config['sample_profile_ID']
    sample_file = config['sample_file']
    seq_depth = config['sequencing_depth']

    train_chr, valid_chr = train_valid_chrs.get_train_valid_chrs()
    all_chr = merge_dicts(train_chr, valid_chr)
    simulate_reads_hifi(datadir_path, chrs_path, all_chr, assembler, pbsim3_dir, sample_profile_id, sample_file, depth=seq_depth)
    generate_graphs_hifi(datadir_path, all_chr, assembler, threads)
