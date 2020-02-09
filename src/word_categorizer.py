import argparse
import os
import pickle

import numpy as np
import random as rand
from sklearn.cluster import KMeans, DBSCAN
from tqdm import tqdm
from scipy import sparse

# My modules
from src.BertLM import BertLM


class WordCategorizer:
    def __init__(self, pretrained_model='bert-base-uncased', device_number='cuda:2', use_cuda=False):

        self.device_number = device_number
        self.use_cuda = use_cuda

        print("Loading BERT model...")
        self.Bert_Model = BertLM(pretrained_model=pretrained_model, device_number=device_number, use_cuda=use_cuda)

        self.vocab = []
        self.matrix = []  # Stores sent probability for each word-sentence pair (rows are words)

    def load_vocabulary(self, vocab_filename):
        """
        Reads vocabulary file. File format must be one word per line, no comments accepted.
        :param vocab_filename:  Path to vocab file
        :return:                None
        """
        with open(vocab_filename, 'r') as fv:
            lines = fv.read().splitlines()
            self.vocab = [l.split()[0] for l in lines]

    def load_matrix(self, vocab_filename, sentences_filename, pickle_filename, num_masks=1, verbose=False):
        """
        If pickle file is present, load data; else, calculate it.
        This method:
        :param sentences
        :param pickle_file_name
        """
        try:
            with open(pickle_filename, 'rb') as h:
                _data = pickle.load(h)
                self.vocab = _data[0]
                self.matrix = _data[1]
                self.Bert_Model = _data[2]

                print("MATRIX FOUND!")

        except:
            print("MATRIX File Not Found!! \n")
            print("Performing matrix calculation...")

            self.load_vocabulary(vocab_filename)
            self.populate_matrix(sentences_filename, num_masks=num_masks, verbose=verbose)

            with open(pickle_filename, 'wb') as h:
                _data = (self.vocab, self.matrix, self.Bert_Model)
                pickle.dump(_data, h)

            print("Data stored in " + pickle_filename)

    def populate_matrix(self, sents_filename, num_masks=1, sparse_thres=-4, verbose=False):
        """
        Calculates probability matrix for the sentence-word pairs
        Currently can only handle one mask per sentence. We can repeat sentences in the sents_file as
        a workaround to this.
        :param sents_filename:  File with input sentences
        :param num_masks:       Repetitions for each sentence, with different masks
        :param sparse_thres:    If sentence prob is under this value, assign 0
        :return: None
        """
        print("Evaluating word-sentence probabilities")
        num_sents = 0
        with open(sents_filename, 'r') as fs:
            for sent in fs:
                tokenized_sent = self.Bert_Model.tokenize_sent(sent)
                masks_pos = rand.sample(range(1, len(tokenized_sent) - 1), num_masks)  # Don't mask boundary tokens
                for mask_pos in masks_pos:
                    # Calculate sentence probability for each word in current masked position
                    print(f"Evaluating sentence {tokenized_sent} with mask in pos {mask_pos}")
                    sent_row = np.array(
                        [self.process_sentence(tokenized_sent[:], word, mask_pos, verbose=verbose) for word in
                         self.vocab])
                    sent_row = sent_row * (sent_row > sparse_thres)  # Cut low probability values
                    self.matrix.append(sent_row)
                    num_sents += 1

        self.matrix = np.array(self.matrix).astype(np.float32)  # Reduce matrix precision, make rows be word-senses
        self.matrix = sparse.csr_matrix(self.matrix.T)  # Convert to sparse matrix

    def process_sentence(self, tokenized_sent, word, mask_pos, verbose=False):
        """
        Replaces word in mask_pos for input word, and evaluates the sentence probability
        :param tokenized_sent: Input sentence
        :param word: Input word
        :param mask_pos: Position to replace input word
        :param verbose:
        :return:
        """
        tokenized_sent[mask_pos] = word
        curr_prob = self.Bert_Model.get_sentence_prob(tokenized_sent, verbose=verbose)

        return curr_prob

    def cluster_words(self, method='KMeans', **kwargs):
        if method != 'KMeans':
            print("Method not implemented... using KMeans instead")

        print("Clustering word-sense vectors")
        k = kwargs.get('k', 2)  # 2 is default value, if no kwargs were passed
        estimator = KMeans(n_clusters=k, n_jobs=4)
        estimator.fit(self.matrix)  # Transpose matrix to cluster words, not sentences
        return estimator.labels_

    def write_clusters(self, save_to, labels):
        """
        Write clustering results to file
        :param save_to:        Directory to save disambiguated senses
        :param labels:         Cluster labels
        """
        num_clusters = max(labels) + 1
        print(f"Writing {num_clusters} clusters to file")

        # Write word categories to file
        append = "/KMeans_k" + str(num_clusters)
        if not os.path.exists(save_to):
            os.makedirs(save_to)
        with open(save_to + append + '.wordcat', "w") as fo:
            for i in range(-1, num_clusters):  # Also write unclustered words
                cluster_members = [self.vocab[j] for j, k in enumerate(labels) if k == i]
                fo.write(f"Cluster #{i}")
                if len(cluster_members) > 0:  # Handle empty clusters
                    fo.write(": \n[")
                    np.savetxt(fo, cluster_members, fmt="%s", newline=", ")
                    fo.write(']\n')
                else:
                    fo.write(" is empty\n\n")


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='WSD using BERT')
    parser.add_argument('--no_cuda', action='store_false', help='Use GPU?')
    parser.add_argument('--device', type=str, default='cuda:2', help='GPU Device to Use?')
    parser.add_argument('--sentences', type=str, required=True, help='Sentence Corpus')
    parser.add_argument('--vocab', type=str, required=True, help='Vocabulary Corpus')
    parser.add_argument('--threshold', type=int, default=1, help='Min freq of word to be disambiguated')
    parser.add_argument('--masks', type=int, default=1, help='Min freq of word to be disambiguated')
    parser.add_argument('--clusterer', type=str, default='KMeans', help='Clustering method to use')
    parser.add_argument('--start_k', type=int, default=10, help='First number of clusters to use in KMeans')
    parser.add_argument('--end_k', type=int, default=10, help='Final number of clusters to use in KMeans')
    parser.add_argument('--step_k', type=int, default=5, help='Increase in number of clusters to use')
    parser.add_argument('--save_to', type=str, default='test', help='Directory to save disambiguated words')
    parser.add_argument('--pretrained', type=str, default='bert-large-uncased', help='Pretrained model to use')
    parser.add_argument('--pickle_file', type=str, default='test.pickle', help='Pickle file of Bert Embeddings/Save '
                                                                               'Embeddings to file')

    args = parser.parse_args()

    wc = WordCategorizer()
    for _ in tqdm(range(1)):
        wc.load_matrix(args.vocab, args.sentences, args.pickle_file, num_masks=args.masks, verbose=False)

    print("Start clustering...")
    for curr_k in tqdm(range(args.start_k, args.end_k + 1, args.step_k)):
        print(f"Clustering with k={curr_k}")
        cluster_labels = wc.cluster_words(method=args.clusterer, k=curr_k)
        wc.write_clusters(args.save_to, cluster_labels)
