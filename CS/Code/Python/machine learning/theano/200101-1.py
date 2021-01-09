from theano.compile.mode import *
from theano import tensor as T
#不可用
x = T.scalar(name='input', dtype='float64')
w = T.scalar(name='weight', dtype='float64')
b = T.scalar(name='bias', dtype='float64')
z = w * x + b

net_input = theano.function(inputs=[w, x, b], outputs=z)
print('net_input: %2f' % net_input(2.0, 3.0, 0.5))

net_input
