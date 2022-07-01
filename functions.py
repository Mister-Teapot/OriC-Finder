import re
import numpy as np

from itertools import combinations, product
from Bio import SeqIO, Entrez, Seq
from typing import TextIO, Union, Generator
from urllib.error import HTTPError, URLError
import socket

# Self-made module
from peak import Peak


def connected_to_internet() -> bool:
    """Simple check for internet connection. Can return false-positive in case of server within local network."""
    try:
        host = socket.gethostbyname('one.one.one.one')
        with socket.create_connection((host, 80), 2) as connection:
            connection.close()
        return True
    except Exception: pass
    return False


def fetch_file(accession: str, email: str, api_key: Union[str, None], rettype: str) -> TextIO:
    """Downloads the given file_tpye of the given accession in temporary memory"""
    Entrez.email = email
    if api_key is not None: Entrez.api_key = api_key
    try:
        return Entrez.efetch(db="nuccore", id=accession, rettype=rettype, retmode="text")
    except HTTPError as BadRequest:
        (api_message_1, api_message_2) = (f' with API_key \'{api_key}\'', ' and if your API_key if correctly typed and linked to the given email') if api_key is not None else ('', '')
        raise ValueError(f'Unable to fetch accession: \'{accession}\' using \'{email}\'{api_message_1}. Please check if the accession is of an existing chromosomal sequence{api_message_2}.') from BadRequest
    except URLError as NoConnection:
        raise ConnectionError('You are fetching a file from the NCBI servers. Please make sure you have an internet connection to do so.') from NoConnection


def read_FASTA(handle: Union[TextIO, str]) -> tuple:
    """Read a FASTA file and returns the name and sequence of only the first entry in the file"""
    Seq_records = SeqIO.parse(handle, 'fasta')
    Seq_obj = next(Seq_records)
    return Seq_obj.id, Seq_obj.seq 


def read_gene_info(handle: TextIO, genes_list: list) -> dict:
    """Read FASTA-file acquired with rettype='fasta_cds_na'."""
    obj = SeqIO.parse(handle, 'fasta')
    genes = [gene.lower() for gene in genes_list]
    genes_dict = {}
    num_of_genes = 0
    for gene in obj:
        num_of_genes += 1
        features = [x.split('=') for x in re.findall(r"\[(.*?)\]", gene.description) if '=' in x]
        feature_dict = {feature[0] : feature[1] for feature in features}
        try: gene_name = feature_dict.pop('gene')
        except KeyError:
            try: gene_name = feature_dict['protein'].split(' ')[0]
            except KeyError: continue
        if gene_name.lower() in genes:
            genes_dict.update({gene_name : feature_dict})
    return genes_dict, num_of_genes


def extract_locations(seq_len: int, genes_dict: dict) -> list:
    """Returns Peaks of the middle position of every gene in the dictionary."""
    locations = []
    for gene_dict in genes_dict.values():
        clean_locs = handle_location(gene_dict['location'], seq_len)
        if clean_locs is None:
            return None
        locations.extend(clean_locs)
    middles = [Peak(Peak.get_middle(loc[0], loc[1], seq_len), seq_len, 0) for loc in locations]
    return middles


def handle_location(location: str, seq_len: int) -> list:
    """
    Gene locations come in a billion flavours due to different annotation options. This function handles the vast majority of cases.
    Biopython can parse all location formats (AFAIK), but I can't find how to access their parsers, since they're hidden/private in some of the classes
    """
    handled = []
    if re.search(r'[^joincmplemt<>,\s\d\(\)\.]', location) is not None:
        return None
    loc_groups = _split_location(location)
    for loc_lst in loc_groups:
        if len(loc_lst) == 1:
            loc_coords = re.findall(r'\d+', loc_lst[0])
            if len(loc_coords) == 0:
                return None
            if len(loc_coords) == 1:
                loc_coords.append(loc_coords[0])
            loc_coords = [int(x) for x in loc_coords]
            handled.append(loc_coords)
        else: # len(i) > 1
            all_nums = [int(y) for x in loc_lst for y in re.findall(r'\d+', x)]
            relevant_idxes = np.unravel_index(get_adj_mat(all_nums, seq_len=seq_len).argmax(), (len(all_nums), len(all_nums)))
            first, second = min(all_nums[relevant_idxes[0]], all_nums[relevant_idxes[1]]), max(all_nums[relevant_idxes[0]], all_nums[relevant_idxes[1]])
            handled.append( [first, second] )
    return handled


def _split_location(location):
    """
    Private: used by handle_location. Splits a `location` string into its location groups.

    (Extreme) e.g.:
    \t`location = 'join(complement(1..>2),3..4,<5..6,500),100..200,join(500..600,complement(0..4))'`\n
    returns:
    \t`[['1..>2', '3..4', '5..6', '500'], ['100..200'], ['500..600', '0..4']]`
    """
    raw_locs = re.split(r',\s?', location)
    locs = []
    done, i = False, 0
    while not done: # join(...) groups suck
        if i > len(raw_locs) - 1:
            break
        if raw_locs[i].count('(') != raw_locs[i].count(')'):
            group_done, j = False, i+1
            while not group_done:
                if j > len(raw_locs) - 1:
                    break
                (group_done, j) = (True, j) if raw_locs[j].count('(') != raw_locs[j].count(')') else (False, j+1)
            locs.append( ','.join([raw_locs[x] for x in range(i, j+1)]) )
            i = j+1
        else:
            locs.append(raw_locs[i])
            i += 1
    locs = [re.findall(r'\d+(?:\.\.[<>]?\d+)?', entry) for entry in locs]
    return locs


def get_adj_mat(peaks_a: list, peaks_b: list = None, seq_len: int = None) -> np.ndarray:
    """
    Gets adjacency matrix for given list of `Peak` or `int` objects.
    The matrix can be between a list and the elements of itself or between the elements of two lists.
    All elements in each list must be of the same type.
    Elements in `peaks_a` must be the same type as those in `peaks_b`.
    If elements are integers, `seq_len` must be provided.
    """
    # Error handling
    are_integers = True if isinstance(peaks_a[0], int) else False
    if are_integers and seq_len is None:
        raise ValueError('Provided list of integers, but did not provide `seq_len`.')
    if not all(isinstance(x, type(peaks_a[0])) for x in peaks_a[1:]):
        raise ValueError('Not all elements in `peaks_a` are of the same type.')

    if peaks_b is not None:
        if not all(isinstance(x, type(peaks_a[0])) for x in peaks_a[1:]):
            raise ValueError('Not all elements in `peaks_b` are of the same type.')
        if not isinstance(peaks_b[0], type(peaks_a[0])):
            raise ValueError('Elements is `peaks_a` are not the same type as `peaks_b`.')

        adj_mat = np.zeros((len(peaks_a), len(peaks_b)))
        iterator = product(enumerate(peaks_a), enumerate(peaks_b))
    else:
        adj_mat = np.zeros((len(peaks_a), len(peaks_a)))
        iterator = combinations(enumerate(peaks_a), r=2)

    # The function
    for (i_a, a), (i_b, b) in iterator:
        dist = Peak.calc_dist(a, b, seq_len) if are_integers else Peak.calc_dist(a.middle, b.middle, a.seq_len)
        adj_mat[i_a, i_b] = dist
        if peaks_b is None:
            adj_mat[i_b, i_a] = dist
    return adj_mat


def get_connected_groups(peaks: list, adj_mat: np.ndarray, threshold: int) -> list:
    """Recursively find connected groups in an undirected graph"""
    connected_groups_idx = _get_connected_groups_init(peaks, adj_mat, threshold)
    accepted_groups_idx = []
    for group_idx in connected_groups_idx:
        flag = False
        for i, j in combinations(group_idx, r=2):
            if adj_mat[i][j] > threshold*3:
                group_vals = [peaks[i] for i in group_idx]
                group_matrix = get_adj_mat(group_vals, seq_len=200)
                split_group_idx = _get_connected_groups_init(group_vals, group_matrix, threshold//2)
                split_group = [[group_idx[i] for i in group] for group in split_group_idx]
                accepted_groups_idx.extend(split_group)
                flag = True
                break
        if not flag:
            accepted_groups_idx.append(group_idx)
        else:
            flag = False
            
    connected_groups_vals = [ [peaks[i] for i in idx_group] for idx_group in accepted_groups_idx ]
    return connected_groups_vals


def _get_connected_groups_init(peaks: list, adj_mat: np.ndarray, threshold: int) -> list:
    """Private: Groups initial indices of `peaks`."""
    visited = [False] * len(peaks)
    connected_groups_idx = []
    for i in range(len(peaks)):
        if not visited[i]:
            group = []
            _, _, visited, group, _ = _DFS_recurse(i, adj_mat, visited, group, threshold=threshold)
            connected_groups_idx.append(group)
    return connected_groups_idx


def _DFS_recurse(idx, adj_mat, visited, connected_list, threshold):
    """Private: used by _get_connected_groups_init for recursion"""
    visited[idx] = True
    connected_list.append(idx)
    for i in range(len(visited)):
        if i == idx:
            continue
        elif adj_mat[i][idx] <= threshold and not visited[i]:
            _, _, visited, connected_list, _ = _DFS_recurse(i, adj_mat,visited, connected_list, threshold)
    return idx, adj_mat, visited, connected_list, threshold

# peaks = [1,2,3,4,5,7,8,9,10,11, 50,51,52, 100,101,102, 200]
# mat = get_adj_mat(peaks, seq_len=200)
# print(get_connected_groups(peaks, mat, threshold=2))

def binary_search(arr: list, x) -> Union[int, None]:
    """Return index of `x` in `arr`. None, if `x` not in `arr`. Search done iteratively."""
    low, mid, high = 0, 0, len(arr)-1
    while low <= high:
        mid = (high + low) // 2
        if arr[mid] < x: low = mid + 1
        elif arr[mid] > x: high = mid - 1
        else: return mid
    return None


def generate_mismatched_strings(string: str, mismatches: int = 2) -> Generator:
    string_len = len(string)
    letters = 'ACGT'

    for indices in combinations(range(string_len), mismatches):
        for replacements in product(letters, repeat=mismatches):
            skip = False
            for i, a in zip(indices, replacements):
                if string[i] == a:
                    skip = True
            if skip:
                continue

            keys = dict(zip(indices, replacements))
            yield ''.join([string[i] if i not in indices else keys[i] for i in range(string_len)])


def get_dnaa_boxes(box_list: list, max_mismatches: int = 2) -> set:
    """
    Standard parameters: Get all unique dnaa-box 9-mers and reverse complements that allow for 0, 1, or 2 mismatches.
    Sources as comments in function.

    Parameters:
    - `box_list`       : list with strings of dnaa-boxes to use. Make sure all given boxes are 9 bases long.
    - `max_mismatches` : maximum allowed mismatches in dnaa-box that is still seen as an accepted dnaa-box.
        E.g. 2 allows all kmers that have 0, 1 or 2 mismatches with the dnaa-box.\n
    Return:
        `dnaa_boxes`   : set of 9-mers matching the given parameters.
    """

    #             Sequences                       DOI                                            Year  Notes
    consensus_1 = ['TTAT(A|C)CA(A|C)A']         # https://doi.org/10.1016/0092-8674(84)90284-8  (1984) The first consensus
    consensus_2 = ['TGTG(G|T)ATAAC']            # https://doi.org/10.1016/0022-2836(85)90299-2  (1985) Matsui-box
    consensus_3 = ['TTAT(A|T|C|G)CACA']         # https://doi.org/10.1093/dnares/dsm017         (2007) In (roughly) all eubacteria, not just B. subtilis
    consensus_4 = [                             # https://doi.org/10.1093/emboj/16.21.6574      (1997) Affinity study
        'TTATCCACA', 'TTTTCCACA', 'TTATCAACA',
        'TCATTCACA', 'TTATACACA', 'TTATCCAAA'
    ]
    consensus_5 = [                             # https://doi.org/10.1007/BF00273584            (1991) Only in E. coli K12. Do not use.
        '(T|C)(T|C)(A|T|C)T(A|C)C(A|G)(A|C|T)(A|C)'
    ]

    '''
    Useful acticles about DnaA(-boxes):
    - https://doi.org/10.1101/cshperspect.a012922
    - https://doi.org/10.1093/nar/gkr832
    - https://doi.org/10.3389/fmicb.2018.00319
    - https://doi.org/10.1046/j.1365-2958.1996.6481362.x.
    '''

    # Get all dnaa-boxes as strings
    boxes = box_list.copy()
    for box in box_list:
        if re.search(r'[^ATCG]', box) is not None:
            raise ValueError(f'\n\tInput string: \'{box}\' contains forbidden characters. Only use the four nucleotide bases: A, T, C, and G.')
        if len(box) != 9:
            raise ValueError(f'Input string \'{box}\' not of length 9.')
        # Also check reverse complement for box on other strand
        boxes.append(str(Seq.Seq(box).reverse_complement()))

    # Get all unique strings while allowing for max. 2 mismatches.
    mismatch_boxes = list(set(boxes))
    for box in boxes:
        for i in range(abs(max_mismatches)):
            mismatch_boxes.extend(list(generate_mismatched_strings(box, i+1)))
    return set(mismatch_boxes)