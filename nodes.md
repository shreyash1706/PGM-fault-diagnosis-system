

###  Designing the Probabilistic Graphical Model (PGM)

A Bayesian Network (your PGM) is a Directed Acyclic Graph (DAG). It consists of **Nodes** (variables) and **Edges** (arrows representing cause-and-effect).

To design this, we must split your nodes into two distinct categories: **Latent Nodes** (the hidden faults we want to diagnose) and **Observable Nodes** (the metrics we can actually see in cAdvisor/Kafka).

Here is the exact blueprint for your network.

#### The Latent Nodes (Root Causes / Faults)

These are the nodes at the very top of your graph. They are binary (True/False). Your ML model will output the probability of these being `True`.

1. **Node: `Compute_Overload**` (Simulating the CPU spike)
2. **Node: `Memory_Leak**` (Simulating resource exhaustion)
3. **Node: `Network_Partition**` (Simulating delayed routing or database lag)
4. **Node: `App_Crash**` (Simulating the code throwing 500 Internal Server Errors)

#### The Observable Nodes (Symptoms / Metrics)

These are the nodes at the bottom of the graph. You will feed live data from Kafka into these nodes. To keep the math simple, we will categorize the continuous numerical data into discrete states (e.g., instead of feeding the model "85% CPU", you feed it "High").

1. **Node: `CPU_Usage**` (States: Normal, High, Critical)
2. **Node: `RAM_Usage**` (States: Normal, High, Critical)
3. **Node: `API_Latency**` (States: Normal, Elevated, Timeout)
4. **Node: `Error_Rate**` (States: Zero, Spiking)

#### Defining the Causal Edges (The Arrows)

The true power of the PGM is defining *how* faults create overlapping symptoms. By drawing these arrows, you teach the model the physics of your server environment.

Here is how the causes map to the effects:

* **`Compute_Overload` $\rightarrow$ causes $\rightarrow$ `CPU_Usage` (High)**
* **`Compute_Overload` $\rightarrow$ causes $\rightarrow$ `API_Latency` (Elevated)**
*(When CPU maxes out, it takes longer to process web requests).*
* **`Memory_Leak` $\rightarrow$ causes $\rightarrow$ `RAM_Usage` (Critical)**
* **`Memory_Leak` $\rightarrow$ causes $\rightarrow$ `API_Latency` (Elevated)**
*(When RAM is full, the system constantly swaps memory to the hard drive, slowing everything down).*
* **`Network_Partition` $\rightarrow$ causes $\rightarrow$ `API_Latency` (Timeout)**
*(CPU and RAM remain totally normal, but the app hangs waiting for the database).*
* **`Network_Partition` $\rightarrow$ causes $\rightarrow$ `Error_Rate` (Spiking)**
*(Eventually, those hanging requests drop and throw 504 Gateway Timeouts).*
* **`App_Crash` $\rightarrow$ causes $\rightarrow$ `Error_Rate` (Spiking)**
*(Latency, CPU, and RAM might be perfectly fine, but the logic is broken).*

### How the Inference Works

When your Kafka stream passes a real-time observation into the bottom nodes—for example, it sets `CPU_Usage = Normal`, `RAM_Usage = Critical`, and `API_Latency = Elevated`—the model mathematically works backward up the arrows.

It calculates the posterior probability using Bayes' theorem: $P(\text{Fault} | \text{Symptoms})$. Because it knows that a Compute Overload *should* have spiked the CPU, it heavily penalizes that fault, leaving `Memory_Leak` as the mathematically dominant diagnosis.

