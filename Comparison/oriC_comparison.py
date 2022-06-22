import os, sys
from ast import literal_eval
import pandas as pd

# Pandas printing options
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', 15)

# Self-made module
#   Local path
sys.path.append('../OriC_Finder')
#   Cluster path
# sys.path.append('/tudelft.net/staff-umbrella/GeneLocations/ZoyavanMeel/OriC_Finder/')
import oriC_Finder as of
from peak import Peak
import plotting_functions as pf

MAX_DIST = 2.5/100
VERSION  = 'v4'


def make_comparator_csv(Z_curve_csv, DoriC_csv, comparator_csv):
    '''Merges Z_curve_csv and DoriC_csv into one csv and/or dataframe for comparison with compare_dbs'''

    # Read CSVs
    Z_curve_df = pd.read_csv( Z_curve_csv )
    DoriC_df   = pd.read_csv( DoriC_csv )

    # Drop empty columns
    Z_curve_df.dropna(axis=1, how='all', inplace=True)

    # Drop duplicate rows
    Z_curve_df.drop_duplicates(subset=['RefSeq'], ignore_index=True, inplace=True)

    # Remove version numbers from accessions
    Z_curve_df['RefSeq'] = Z_curve_df['RefSeq'].str.extract(r'([^.]*)')

    # Merge into single dataframe
    col_names_Z = [x for x in Z_curve_df.columns if x not in ['RefSeq', 'Organism']]
    in_both_df = {x: [] for x in DoriC_df.columns.to_list() + col_names_Z}
    for i, sample in Z_curve_df.iterrows():
        if sample['RefSeq'] in DoriC_df['RefSeq'].to_list():
            for j in col_names_Z:
                in_both_df[j].append( sample[j] )
            for j in DoriC_df.columns.to_list():
                in_both_df[j].append( DoriC_df.loc[DoriC_df['RefSeq'] == sample['RefSeq'], j].values[0] ) # Series.values -> ['element'], very annoying
    
    comparator_df = pd.DataFrame(in_both_df)
    comparator_df.to_csv(comparator_csv, index=False)
    return comparator_df


def compare_dbs(df=None, csv=None, info_file_path=None, print_info=False, max_dist=30000, alt_oriC=None, use_confidence=None, exclude_False_order=False):
    '''
    DEPRECIATED
    Compares results. Results can be loaded from a pandas.DataFrame OR csv.
    info       : If str, writes a text_file to the given location with some info on the analysis.
    print_info : If True, prints the same info that was written to 'info' with print-statements for quick reading.
    max_dist   : Maximum distance two oriCs can have from each other if they want to be matched. If <= 1, will be
                 seen as a fraction of the total sequence length. If > 1, it will be seen as # of basepairs.
    '''

    # Errors and warnings
    if df is None and csv is None:
        raise KeyError('Must load a pandas.DataFrame or CSV file.')
    if df is not None and csv is not None:
        raise KeyError('Load either a pandas.DataFrame or CSV, not both.')
    if csv is not None:
        df = pd.read_csv(csv)

    # Compare predictions (Assuming DoriC as ground truth for now)
    num_of_predictions = [0, 0] # [more oriC in DoriC, more oriC by mine]
    multi_matching = []

    all_distances = {
        'RefSeq'     : [],
        'D_idx'      : [],
        'Z_idx'      : [],
        'Distance_bp': [],
        'Distance_pc': []
    }

    total_D_oriC = 0
    total_Z_oriC = 0
    total_D_by_Z = 0
    total_Z_that_found_a_D = 0
    recall = 0

    for i, sample_original in df.iterrows():
        sample = sample_original.copy()
        sample.dropna(inplace=True)

        seq_len = sample['Sequence_length']
        D_oriC_cols = sorted( [i for i in sample.axes[0] if 'DoriC_oriC' in i], key=lambda x:x[-1] )
        if alt_oriC is None:
            Z_oriC_cols = sorted( [i for i in sample.axes[0] if 'oriC_middle' in i], key=lambda x:x[-1] )#[:2] # only use top 2 oriC if there is more than one
        else:
            Z_oriC_cols = sorted( [i for i in sample.axes[0] if alt_oriC in i], key=lambda x:x[-1] )#[:2]
    
        if len(D_oriC_cols) > len(Z_oriC_cols):
            num_of_predictions[0] += 1
        elif len(D_oriC_cols) < len(Z_oriC_cols):
            num_of_predictions[1] += 1

        D_oriC_middles = [ Peak.get_middle( int( literal_eval(sample[D_oriC_col])[0] ), int( literal_eval(sample[D_oriC_col])[1] ), seq_len ) for D_oriC_col in D_oriC_cols ]
        if use_confidence is not None:
            Z_oriC_middles = [ int(sample[Z_oriC_cols[i]]) for i in range(len(Z_oriC_cols)) if sample[f'Occurance_oriC_{i}'] >= use_confidence]
        else:
            Z_oriC_middles = [ int(sample[Z_oriC_cols[i]]) for i in range(len(Z_oriC_cols))]
        if exclude_False_order and sample['False_order']:
            Z_oriC_middles = []
        total_D_oriC += len(D_oriC_cols)
        total_Z_oriC += len(Z_oriC_middles)
        if len(Z_oriC_middles) > 0:
            recall += 1

        ### Accuracy per point: how many points were properly matched
        window_size = max_dist if max_dist > 1 else int(seq_len * max_dist)
        for i in range(len(D_oriC_middles)):
            D_oriC_middles[i] = Peak(D_oriC_middles[i], seq_len, window_size)
        for i in range(len(Z_oriC_middles)):
            Z_oriC_middles[i] = Peak(Z_oriC_middles[i], seq_len, window_size)

        # Match all Z_oriC to D_oriC
        all_matches = of.match_peaks(D_oriC_middles, Z_oriC_middles)

        # Only work with top_matches for now (it does not differ from all_matches right now)
        D_appearances = [match[0] for match in all_matches]
        Z_appearances = [match[1] for match in all_matches]
        total_D_by_Z += len(D_appearances)
        total_Z_that_found_a_D += len(set(Z_appearances))
        multi_matching.append( ( len(D_appearances) != len(set(D_appearances)), len(Z_appearances) != len(set(Z_appearances)) ) )

        for i, D_oriC in enumerate(D_oriC_middles):
            distances_basepair = []
            distances_percent  = []
            for j, Z_oriC in enumerate(Z_oriC_middles):
                distances_basepair.append( (j, Peak.calc_dist(D_oriC.middle, Z_oriC.middle, seq_len) ) )
                distances_percent.append( (j, int( 100 * Peak.calc_dist(D_oriC.middle, Z_oriC.middle, seq_len)/seq_len ) ) )
            if len(distances_basepair) != 0:
                sorted_dists_bp = min(distances_basepair, key=lambda x:abs(x[1]))
                sorted_dists_pc = min(distances_percent, key=lambda x:abs(x[1]))

                all_distances['RefSeq'].append(sample['RefSeq'])
                all_distances['D_idx'].append(i)
                all_distances['Z_idx'].append(sorted_dists_bp[0])
                all_distances['Distance_bp'].append(sorted_dists_bp[1])
                all_distances['Distance_pc'].append(sorted_dists_pc[1])

    # Information
    info_lines = ['INFORMATION']
    info_lines.append( f'There were {df.shape[0]} organisms.' )
    info_lines.append( f'\t{df.shape[0] - sum(num_of_predictions)} times both databases predicted the same amount of oriCs.' )
    info_lines.append( f'\t{num_of_predictions[0]} times DoriC predicted more oriCs.' )
    info_lines.append( f'\t{num_of_predictions[1]} times mine predicted more oriCs.\n' )

    info_lines.append( f'There were a total of {total_D_oriC} oriCs predicted by DoriC' )
    info_lines.append( f'There were a total of {total_Z_oriC} oriCs predicted by my predictor\n' )

    multi_match_D = [match[0] for match in multi_matching if match[0]]
    multi_match_Z = [match[1] for match in multi_matching if match[1]]
    disp_dist = f'{max_dist*100} % of the sequence length' if max_dist <= 1 else f'{max_dist} bp'

    info_lines.append('vvv')
    info_lines.append( f'{total_D_by_Z} out of {total_D_oriC} ({total_D_by_Z/total_D_oriC*100:.2f} %) DoriC oriCs were found by my predictor with max accepted distance of {disp_dist}' )
    info_lines.append( f'{total_Z_that_found_a_D} out of {total_Z_oriC} ({total_Z_that_found_a_D/total_Z_oriC*100:.2f} %) Z_oriCs found a D_oriC with max accepted distance of {disp_dist}' )
    info_lines.append('^^^\n')

    info_lines.append( f'{len(multi_match_D)} DoriC oriC were matched to mutliple Z_oriC. (> 0 is not okay)' )
    info_lines.append( f'\tThis means there are Z_oriC that are closer than {disp_dist} to each other.') if len(multi_match_D) > 0 else None
    info_lines.append( f'{len(multi_match_Z)} Z_oriC were matched to mutliple DoriC oriC. (> 0 is okay)' )
    info_lines.append( f'\tThis means there are DoriC oriC that are closer than {disp_dist} to each other.\n') if len(multi_match_Z) > 0 else None

    info_lines.append( f'The Z_oriC was off by {sum(all_distances["Distance_bp"])/len(all_distances["Distance_bp"]):.2f} bp on average.' )
    info_lines.append( f'The Z_oriC was off by {sum(all_distances["Distance_pc"])/len(all_distances["Distance_pc"]):.2f} % of the genome on average.' )

    if info_file_path is not None:
        with open(info_file_path, 'w') as fh:
            fh.write('\n'.join(info_lines))
    if print_info:
        print('\n'.join(info_lines))

    csv_line = f'{use_confidence},{total_D_by_Z/total_D_oriC*100:.2f},{total_Z_that_found_a_D/total_Z_oriC*100:.2f},{ sum(all_distances["Distance_bp"])/len(all_distances["Distance_bp"]) },{ sum(all_distances["Distance_pc"])/len(all_distances["Distance_pc"]) },{total_D_oriC},{recall},{df.shape[0]}'
    print(csv_line)

    return pd.DataFrame(all_distances)


def precision_recall(df, max_dist, alt_oriC=None, use_confidence=None):
    '''Uses top oriC of prediction to compare to DoriC. Only takes max_dist as fraction of genome length.'''
    TP, TN, FP, FN = 0, 0, 0, 0

    all_distances = {
        'RefSeq'     : [],
        'D_idx'      : [],
        'Distance_bp': [],
        'Distance_pc': []
    }

    for i, sample_original in df.iterrows():
        sample = sample_original.copy()
        sample.dropna(inplace=True)
        seq_len = sample['Sequence_length']

        D_oriC_cols = sorted( [i for i in sample.axes[0] if 'DoriC_oriC' in i], key=lambda x:x[-1] )
        D_oriC_middles = [ Peak.get_middle( int( literal_eval(sample[D_oriC_col])[0] ), int( literal_eval(sample[D_oriC_col])[1] ), seq_len ) for D_oriC_col in D_oriC_cols ]

        # name of column to use
        Z_oriC_col = 'oriC_middles_0' if alt_oriC is None else alt_oriC
        Z_oriC_middle = int(sample[Z_oriC_col]) if use_confidence is None or sample[f'Occurance_oriC_0'] >= use_confidence else None

        if Z_oriC_middle is None:
            FN += len(D_oriC_middles)
        else:
            window_size = int(seq_len * max_dist)
            for i in range(len(D_oriC_middles)):
                D_oriC_middles[i] = Peak(D_oriC_middles[i], seq_len, window_size)
            Z_oriC = Peak(Z_oriC_middle, seq_len, window_size)

            for i, D_oriC in enumerate(D_oriC_middles):
                distance_basepair = Peak.calc_dist(D_oriC.middle, Z_oriC.middle, seq_len)
                distance_percent  = int( 100 * Peak.calc_dist(D_oriC.middle, Z_oriC.middle, seq_len)/seq_len )

                if distance_percent <= max_dist: TP += 1
                else: FP += 1

                all_distances['RefSeq'].append(sample['RefSeq'])
                all_distances['D_idx'].append(i)
                all_distances['Distance_bp'].append(distance_basepair)
                all_distances['Distance_pc'].append(distance_percent)
    precision = TP / (TP + FP)
    recall = TP / (TP + FN)
    return pd.DataFrame(all_distances), precision, recall


if __name__ == '__main__':
    # Input paths
    Z_curve_csv = 'NCBI data prep/oriC_predictions_'+VERSION+'_csvs/Predicted_DoriC_accessions.csv'#Predicted_4k.csv'
    DoriC_csv   = 'DoriC data prep/DoriC_oriC_concat_entries.csv'

    # Output paths
    comparator_csv = 'Comparison/'+VERSION+'/in_both_sets_all.csv'
    all_file_path  = 'Comparison/'+VERSION+'/comparison_info_file_all.txt'
    exp_file_path  = 'Comparison/'+VERSION+'/comparison_info_file_experimental.txt'
    point_six_file_path  = 'Comparison/'+VERSION+'/comparison_info_file_0.6.txt'

    # Make or load csv
    #comparator_df = make_comparator_csv(Z_curve_csv, DoriC_csv, comparator_csv=comparator_csv)
    comparator_df = pd.read_csv(comparator_csv)

    # General info
    avg_seq_len = comparator_df['Sequence_length'].sum() // comparator_df.shape[0]
    disp_dist   = f'{MAX_DIST*100} % of the sequence length' if MAX_DIST <= 1 else f'{MAX_DIST} bp'
    print('Max genome length          :', comparator_df['Sequence_length'].max())
    print('Min genome length          :', comparator_df['Sequence_length'].min())
    print('Mean genome length         :', avg_seq_len)
    print('Deviation in genome length :', int(comparator_df['Sequence_length'].std()))
    print('Genome size is not very consistent. The max distance that two oriC can be from each other will')
    print(f'be set to {disp_dist} of the total genome length rather than a fixed number for all genomes.\n')

    steps = 100
    p_r_dict = {'min_confidence': [x for x in range(steps+1)]}
    for v in ['v3', 'v4']:
        p_r_dict[f'precision_{v}'] = []
        p_r_dict[f'recall_{v}'] = []
        comparator_df = pd.read_csv('Comparison/'+v+'/in_both_sets_all.csv')
        for i in range(steps+1):
            distances, precision, recall = precision_recall(comparator_df, MAX_DIST, use_confidence=i/steps)
            p_r_dict[f'precision_{v}'].append(precision*100)
            p_r_dict[f'recall_{v}'].append(recall*100)

    pd.DataFrame(p_r_dict).to_csv('Comparison/version_3_and_4_precision_recall.csv', index=False)

    # ALL DATA
    # v3 = pd.read_csv('Comparison/v3/in_both_sets_all.csv')['RefSeq']
    # comparator_df = comparator_df[comparator_df['RefSeq'].isin(v3)]
    # for i in range(11):
    #     hist_all_df = compare_dbs(df=comparator_df, info_file_path=None, print_info=False, max_dist=MAX_DIST, alt_oriC='oriC_middles_0', use_confidence=i/10, exclude_False_order=False)
    # hist_all_df.to_csv('Comparison/'+VERSION+'/hist_all_df.csv', index=False)
    # hist_all_df = pd.read_csv('Comparison/'+VERSION+'/hist_all_df.csv')
    # pf.distance_histogram(hist_all_df, log=True)
    # pf.distance_histogram(hist_all_df, log=False)

    # # All the same steps, but only the EXPERIMENTAL DATA
    # exp_refseq = [ # Accessions that have been experimentally verified.
    #     'NC_000964', 'NC_002947', 'NC_003272', 'NC_003869', 'NC_003888', 'NC_005090', 'NC_006461', 'NC_007633', 'NC_000913', 'NC_003047',
    #     'NC_007604', 'NC_000962', 'NC_002696', 'NC_002971', 'NC_005363', 'NC_008255', 'NC_009850', 'NC_010546', 'NC_010547', 'NC_011916', NC_000117
    # ]
    # experiment_df = comparator_df[comparator_df['RefSeq'].isin(exp_refseq)]
    # hist_exp_df = compare_dbs(df=experiment_df, info_file_path=None, print_info=True, max_dist=MAX_DIST, use_confidence=0.33)
    # # pf.distance_histogram(hist_exp_df, log=True)
    # pf.distance_histogram(hist_exp_df, log=False)

