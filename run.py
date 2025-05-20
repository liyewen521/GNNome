import argparse
import os
import subprocess

from create_inference_graphs import create_inference_graph
from inference import inference


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-r', '--reads', required=True, type=str, help='Path to the reads')
    parser.add_argument('--asm', type=str, help='Assembler used')
    parser.add_argument('-o', '--out', type=str, default='.', help='Output directory')
    parser.add_argument('-t', '--threads', type=str, default=1, help='Number of threads to use')
    parser.add_argument('-m', '--model', type=str, default='weights/weights.pt', help='Path to the model')
    args = parser.parse_args()

    reads = args.reads
    assembler = args.asm
    out = args.out
    threads = args.threads
    model = args.model

    # Step 1
    print(f'\nStep 1: Running {assembler} on {reads} to generate the graph')
    if assembler == 'hifiasm':
        asm_out = f'{out}/hifiasm/output'
        if not os.path.isdir(asm_out):
            os.makedirs(asm_out)
        subprocess.run(f'./vendor/hifiasm-0.18.8/hifiasm --prt-raw -o {asm_out}/asm -t{threads} -l0 {reads}', shell=True, check=True)
    elif assembler == 'raven':
        asm_out = f'{out}/raven/output'
        if not os.path.isdir(asm_out):
            os.makedirs(asm_out)
        raven_output_prefix = os.path.join(asm_out, "asm")
        raven_cmd = f'./vendor/raven-1.8.1/build/bin/raven -t {threads} -p0 "{reads}" > "{raven_output_prefix}"'
        subprocess.run(raven_cmd, shell=True, check=True)
    else:
        print(f'Error: Assembler {assembler} not recognized. Please use hifiasm or raven.')
        exit(1)

    # Step 2
    print(f'\nStep 2: Preparing the graph for the inference')
    gfa = f'graph_1.gfa'
    create_inference_graph(gfa, reads, out, assembler)
    
    # Step 3
    print(f'\nStep 3: Using the model {model} to run inference on {reads}')
    inference(data_path=out, assembler=assembler, model_path=model, savedir=os.path.join(out, assembler))

    asm_dir = f'{out}/{assembler}/assembly'
    print(f'\nDone!')
    print(f'Assembly saved in: {asm_dir}/0_assembly.fasta')
    print(f'Thank you for using GNNome!')
