import numpy as np
import matplotlib.pyplot as plt

x=np.arange(-6,6,0.1)
y=np.sin(x)

plt.plot(x,y)
plt.xlabel("x")
plt.ylabel("y")
#plt.show()

#sigmoid function

def sigmoid(x):
    return 1.0 / (1 + np.exp(-x))


sigmoid_inputs = np.arange(-10, 10, 0.1)
sigmoid_outputs = sigmoid(sigmoid_inputs)
print("Sigmoid Function Input :: {}".format(sigmoid_inputs))
print("Sigmoid Function Output :: {}".format(sigmoid_outputs))

plt.plot(sigmoid_inputs, sigmoid_outputs)
plt.xlabel("Sigmoid Inputs")
plt.ylabel("Sigmoid Outputs")
plt.legend()
plt.show()