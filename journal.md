# Experiments in word category creation with transformers
###### Journal by glicerico

## Jan 2020
Start experiments using BERT, since it's what people were using in their 
word sense disambiguation experiments (Wiedemman et al. 2019).

The general idea here is that BERT (and other transformer models) have shown 
great language abstraction capabilities.
However, those abstractions don't seem to be found in the attention layers in
a straightforward manner (see Clarke et al. 2019, Htut et al. 2019), and not
easily extractable in an unsupervised manner (for supervised mapping of the
syntactic knowledge learned by BERT, see Hewitt and Manning 2019).
Thus, Ben proposes to use external statistical methods to "milk" the syntactic
relationships that we are looking for out of BERT.

Based on the code by Wiedemann et al. (2019, github.com/uhh-lt/bert-sense), I 
first updated [Bert_Model.py](src/Bert_Model.py) to use the latest huggingface transformers models 
(github.com/huggingface/transformers) and to be able to run without CUDA 
(fixed a bug).
The obtained results were not exactly the same as their paper, but quite close.
I blame the change of transformers versions for the slight difference.

Then, I wanted to test my idea of just getting embeddings for every word
in the corpus, then cluster them and hope that word categories will appear
as a result.
This idea is coming from the previous use of word2vec and AdaGram vectors
for word categorization. 
The code for this attempts is at [all_word_senses.py](src/all_word_senses.py).
Some of the design decisions made were:
- Use the concatenation of the last 4 attention layers for embeddings, 
like bert-sense and the original BERT paper (Devlin et al 2018).
- For words split into sub-components by the BERT tokenizer, use
the arithmetic average of the embeddings of each sub-token, like bert-sense.
- Tried clustering with KMEANS, DBSCAN, OPTICS models in scikit's sklearn
libraries.
- Truncated the precision of the word embeddings to float32 and 5 decimal
places, to try to make processing more efficient. Would be a good idea to
confirm this doesn't affect results.
- Use the cosine distance metric in clustering.

After these attempts, 
at least two problems were noted:
1) Semantic relatedness seems to be an important component of the
embeddings here, while syntactic functions were not clearly distinguished in 
the resulting clusters: words like medicine, medicinal, pharmacist would 
commonly fall in the same cluster.
2) Memory requirements grew very quickly when handling a decent corpus,
since a unique word embedding needs to be stored for each single word 
in the corpus.

So, I decided to proceed with the plan discussed with Ben last week, which
gord more or less like this:

1) Disambiguate words using their unique embeddings: 
come up with a few senses for each word above some frequency threshold.
2) Build a matrix of word-sense-pair similarities by calculating the difference
in sentence probabilities between each word and other words.
3) Use above matrix to get word-sense embeddings.
4) Cluster the vectors to form word categories. Use a Clark-like clustering
method, were not all word-senses will be categorized.

Current work is to implement step 1) above in [WSD.py](src/WSD.py), 
using the following steps:
- First pass
   3) Store sentences in corpus in order 
   1) Calculate and store embeddings for each word in the corpus in a
   nested list [[e1, e2, ..] [e1, e2, ..] .. [e1, e2, ..]]
   2) Store a dictionary with the sentence and word position for each 
   word in the corpus
- Second pass
   1) For each word in vocabulary with more than threshold frequency, 
   gather all its embeddings.
   2) Cluster such embeddings to obtain word senses.
   