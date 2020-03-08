import torch
import numpy as np
from transformers import BertTokenizer, BertModel, BertForMaskedLM

BOS_TOKEN = '[CLS]'
EOS_TOKEN = '[SEP]'
MASK_TOKEN = '[MASK]'


class BERT:
    def __init__(self, pretrained_model='bert-large-uncased', device_number='cuda:2', use_cuda=True,
                 output_hidden_states=True):
        self.device_number = device_number
        self.use_cuda = use_cuda

        self.tokenizer = BertTokenizer.from_pretrained(pretrained_model)
        self.model = BertModel.from_pretrained(pretrained_model, output_hidden_states=output_hidden_states)
        with torch.no_grad():
            self.model.eval()

        if use_cuda:
            self.model.to(device_number)

    def tokenize_sent(self, sentence):
        tokenized_input = self.tokenizer.tokenize(sentence)
        if tokenized_input[0] != BOS_TOKEN:
            tokenized_input.insert(0, BOS_TOKEN)
        if tokenized_input[-1] != EOS_TOKEN:
            tokenized_input.append(EOS_TOKEN)
        return tokenized_input


class BertLM(BERT):
    def __init__(self, pretrained_model='bert-base-uncased', device_number='cuda:2', use_cuda=False):
        BERT.__init__(self, pretrained_model=pretrained_model, device_number=device_number, use_cuda=use_cuda)
        self.model = BertForMaskedLM.from_pretrained(pretrained_model)  # Overwrite model
        with torch.no_grad():
            self.model.eval()

        if use_cuda:
            self.model.to(device_number)

        self.norm_dict = {}

    def print_top_predictions(self, probs, k=5):
        """
        Prints the top-k predicted words contained in probs, and their probabilities.
        :param probs:   A tensor containing the probability for each word in the vocabulary.
                        Probs is calculated via softmax from the logit tensor returned by
                        a masked prediction by the transformer.
        :param k:       Number of top predictions to print
        :return:        Nothing, only prints info
        """
        probs = probs.detach().numpy()
        top_indexes = np.argpartition(probs, -k)[-k:]
        sorted_indexes = top_indexes[np.argsort(-probs[top_indexes])]
        top_tokens = self.tokenizer.convert_ids_to_tokens(sorted_indexes)
        print(f"Ordered top predicted tokens: {top_tokens}")
        print(f"Ordered top predicted values: {probs[sorted_indexes]}")

    def get_directional_prob(self, sm, tokenized_input, i, direction, verbose=False):
        current_tokens = tokenized_input[:]
        if direction == 'backwards':
            current_tokens[1:i + 1] = [MASK_TOKEN for j in range(i)]
        elif direction == 'forward':
            current_tokens[i:-1] = [MASK_TOKEN for j in range(len(tokenized_input) - 1 - i)]
        else:
            print("Direction can only be 'forward' or 'backwards'")
            exit()

        if verbose:
            print()
            print(current_tokens)

        masked_input = torch.tensor([self.tokenizer.convert_tokens_to_ids(current_tokens)])
        predictions = self.model(masked_input)
        predictions = predictions[0]
        probs = sm(predictions[0, i])  # Softmax to get probabilities
        if verbose:
            self.print_top_predictions(probs)

        return probs  # Model predictions

    def calculate_norm_dict(self, sentences_file):
        """
        Determines the normalization score for each sentence length. Sentences_file should
        include grammatical samples of sentences of different length.
        :param sentences_file:  File with sentences to use for normalization scores
        :return:                Dictionary with normalization scores for each sent length
        """
        counts_probs = {}  # Stores counts and sum of probs for sentences of given length
        with open(sentences_file, 'r') as fs:
            for sent in fs:
                tok_sent = self.tokenize_sent(sent)
                tok_len = len(tok_sent)
                if tok_len not in counts_probs:
                    counts_probs[tok_len] = [0, 0]
                counts_probs[tok_len][0] += 1
                counts_probs[tok_len][1] += self.get_sentence_prob_directional(tok_sent)

        print(f"Calculated normalization values for lengths: {counts_probs.keys()}")
        self.norm_dict = {k: v[1] / v[0] for k, v in counts_probs.items()}

    def get_sentence_prob_normalized(self, tokenized_input,  verbose=False):
        """
        Return length-normalized sentence probability. Divides by value in norm_dict
        :param tokenized_input: Input sentence
        :param verbose:
        :return:
        """
        sent_len = len(tokenized_input)  # Num of tokens in sentence (incl boundary tokens)
        score = self.get_sentence_prob_directional(tokenized_input, verbose=verbose)
        if sent_len not in self.norm_dict:
            print("WARNING: No normalization for given sentence length!!\n")
        norm_score = self.norm_dict.get(sent_len, 1)
        return score / norm_score

    def get_sentence_prob_directional(self, tokenized_input, verbose=False):
        """
        Estimate the probability of sentence S: P(S).
        A forward one-directional sentence probability is defined as:
        P_f(S) = P(w_0, w_1, ..., w_N) = P(w_0) * P(w_1|w_0) * P(w_2|w_0, w_1) * ...
        where N is the number of words in the sentence, and each P(w_i|...) is given by a transformer masked
        word prediction with all words to its left masked.
        To take advantage of BERT's bi-directional capabilities, we also estimate the backwards probability:
        P_b(S) = P(w_0, w_1, ..., w_N) = P(w_N) * P(w_{N-1}|w_N) * P(w_{N-2}|w_{N-1}, w_N) * ...
        The sentence probability is the geometric-average of the two directional ones:
        P(S) = sqrt(P_f(S) * P_b(S))
        Hence, one sentence probability requires 2N masked word prediction evaluations.
        :param tokenized_input: Input sentence
        :param verbose: Print information about the obtained probabilities or not.
        :return: Log of geometric average of each prediction: sort of sentence prob. normalized by sentence length.
        """
        sm = torch.nn.Softmax(dim=0)  # used to convert last hidden state to probs

        # Pre-process sentence, adding special tokens
        ids_input = self.tokenizer.convert_tokens_to_ids(tokenized_input)
        if verbose:
            print(f"Processing sentence: {tokenized_input}")

        log_sent_prob_forward = 0
        log_sent_prob_backwards = 0
        # Mask non-special tokens in forward and backwards directions; calculate their probabilities
        for i in range(1, len(tokenized_input) - 1):  # Don't loop first and last tokens
            probs_forward = self.get_directional_prob(sm, tokenized_input, i, 'forward', verbose=verbose)
            probs_backwards = self.get_directional_prob(sm, tokenized_input, i, 'backwards', verbose=verbose)
            log_prob_forward = probs_forward[ids_input[i]]  # Prediction for masked word
            log_prob_forward = np.log10(log_prob_forward.detach().numpy())
            log_prob_backwards = probs_backwards[ids_input[i]]  # Prediction for masked word
            log_prob_backwards = np.log10(log_prob_backwards.detach().numpy())
            log_sent_prob_forward += log_prob_forward
            log_sent_prob_backwards += log_prob_backwards

            if verbose:
                print(f"Word: {tokenized_input[i]} \t Log-Prob_forward: {log_prob_forward}; Log-Prob_backwards: {log_prob_backwards}")

        # Obtain geometric average of forward and backward probs
        log_geom_mean_sent_prob = 0.5 * (log_sent_prob_forward + log_sent_prob_backwards)
        if verbose:
            print(f"Raw forward sentence probability: {log_sent_prob_forward}")
            print(f"Raw backward sentence probability: {log_sent_prob_backwards}\n")
            print(f"Average normalized sentence prob: {log_geom_mean_sent_prob}\n")
        return np.power(10, log_geom_mean_sent_prob)

    def get_sentence_prob_avg_directional(self, tokenized_input, verbose=False):
        """
        Estimate the probability of sentence S: P(S).
        A forward one-directional sentence probability is defined as:
        P_f(S) = [P(w_0, w_1, ..., w_N) = P(w_0) * P(w_1|w_0) * P(w_2|w_0, w_1) * ...] ^ (1/N)
        where N is the number of words in the sentence, and each P(w_i|...) is given by a transformer masked
        word prediction with all words to its left masked. Thus, it's the geometric mean of the individual terms.
        To take advantage of BERT's bi-directional capabilities, we also estimate the backwards probability:
        P_b(S) = P(w_0, w_1, ..., w_N) = P(w_N) * P(w_{N-1}|w_N) * P(w_{N-2}|w_{N-1}, w_N) * ...
        The sentence probability is the geometric-average of the two directional ones:
        P(S) = sqrt(P_f(S) * P_b(S))
        Hence, one sentence probability requires 2N masked word prediction evaluations.
        :param tokenized_input: Input sentence
        :param verbose: Print information about the obtained probabilities or not.
        :return: Log of geometric average of each prediction: sort of sentence prob. normalized by sentence length.
        """
        sm = torch.nn.Softmax(dim=0)  # used to convert last hidden state to probs

        # Pre-process sentence, adding special tokens
        sent_len = len(tokenized_input)
        ids_input = self.tokenizer.convert_tokens_to_ids(tokenized_input)
        if verbose:
            print(f"Processing sentence: {tokenized_input}")

        sent_prob_forward = 1
        sent_prob_backwards = 1
        # Mask non-special tokens in forward and backwards directions; calculate their probabilities
        for i in range(1, len(tokenized_input) - 1):  # Don't loop first and last tokens
            probs_forward = self.get_directional_prob(sm, tokenized_input, i, 'forward', verbose=verbose)
            probs_backwards = self.get_directional_prob(sm, tokenized_input, i, 'backwards', verbose=verbose)
            prob_forward = probs_forward[ids_input[i]]  # Prediction for masked word
            prob_backwards = probs_backwards[ids_input[i]]  # Prediction for masked word
            sent_prob_forward *= np.power(prob_forward.detach().numpy(), 1 / sent_len)
            sent_prob_backwards *= np.power(prob_backwards.detach().numpy(), 1 / sent_len)

            if verbose:
                print(f"Word: {tokenized_input[i]} \t Prob_forward: {prob_forward}; Prob_backwards: {prob_backwards}")

        # Obtain geometric average of forward and backward probs
        geom_mean_sent_prob = np.sqrt(sent_prob_forward * sent_prob_backwards)
        if verbose:
            print(f"Geometric-mean forward sentence probability: {sent_prob_forward}")
            print(f"Geometric-mean backward sentence probability: {sent_prob_backwards}\n")
            print(f"Average normalized sentence prob: {geom_mean_sent_prob}\n")
        return geom_mean_sent_prob

    def get_sentence_prob_bidirectional(self, tokenized_input, verbose=False):

        """
        Estimate the sentence probability P(S), where S is a sentence.
        This probability is composed by using the given transformer model's predictions, as follows:
        P(S) = Prod_i(P(w_i|w_0, w_1,..,w_i-1,w_i+1,..,w_N)),
        where N is the number of words in the sentence, and each P(w_i|...) is given by a transformer masked
        word prediction.
        Hence, one sentence probability requires N masked word prediction evaluations.
        :param tokenized_input: Input sentence
        :param verbose: Print information about the obtained probabilities or not.
        :return: Log of geometric average of each prediction: sort of sentence prob. normalized by sentence length.
        """
        sm = torch.nn.Softmax(dim=0)  # used to convert last hidden state to probs

        # Pre-process sentence, adding special tokens
        sent_len = len(tokenized_input)
        ids_input = self.tokenizer.convert_tokens_to_ids(tokenized_input)
        if verbose:
            print(f"Processing sentence: {tokenized_input}")

        sum_lp = 0
        # Mask non-special tokens and calculate their probabilities
        for i in range(1, len(tokenized_input) - 1):  # Ignore first and last tokens
            current_tokenized = tokenized_input[:]
            current_tokenized[i] = MASK_TOKEN
            masked_input = torch.tensor([self.tokenizer.convert_tokens_to_ids(current_tokenized)])
            predictions = self.model(masked_input)[0]
            current_probs = sm(predictions[0, i])  # Softmax to get probabilities
            current_prob = current_probs[ids_input[i]]  # Prediction for masked word

            sum_lp += np.log(current_prob.detach().numpy())

            if verbose:
                print(current_tokenized)
                print(f"Word: {tokenized_input[i]} \t Prob: {current_prob}")
                self.print_top_predictions(current_probs)

        if verbose:
            print(f"\nNormalized sentence prob: log(P(sentence)) / sent_length: {sum_lp / sent_len}\n")

        return sum_lp / sent_len
