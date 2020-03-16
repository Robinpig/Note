import torch
import torch.nn as nn
fc=nn.Linear(in_features=4,out_features=3)
t=torch.tensor([1,2,3,4],dtype=torch.float32)
output=fc(t)
print(output)