"""Masked PPO on complete expression episodes, with frozen pool observations.

Monte Carlo returns use gamma=1 and a single terminal reward; intermediate
rewards are zero. No gradient flows through the evaluator or Top K.
"""
import hashlib
import random

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical

from .expressions import ExpressionSpace


class ActorCritic(nn.Module):
    def __init__(self, vocabulary, p):
        super().__init__()
        self.embedding = nn.Embedding(vocabulary + 1, 8, padding_idx=0)
        count = p.max_tokens * (1 + p.max_factors)
        self.encoder = nn.Sequential(nn.Linear(count*9+p.max_factors, 64), nn.Tanh(), nn.Linear(64, 64), nn.Tanh())
        self.actor, self.critic = nn.Linear(64, vocabulary), nn.Linear(64, 1)

    def forward(self, tokens, valid, weights, mask):
        x = torch.cat([self.embedding(tokens).flatten(1), valid, weights], dim=1)
        x = self.encoder(x)
        return Categorical(logits=self.actor(x).masked_fill(~mask, -1e9)), self.critic(x).squeeze(-1)


class PPOTrainer:
    def __init__(self, p):
        self.p, self.space = p, ExpressionSpace(p)
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        random.seed(p.seed)
        np.random.seed(p.seed)
        torch.manual_seed(p.seed)
        self.model = ActorCritic(len(self.space.vocabulary), p)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=p.learning_rate)
        self.last_updated_batch = 0

    def parameter_digest(self):
        h = hashlib.sha256()
        for v in self.model.state_dict().values():
            h.update(v.detach().cpu().numpy().tobytes())
        return h.hexdigest()

    def observation(self, prefix, pool):
        tokens = [0] * (self.p.max_tokens * (1+self.p.max_factors))
        for i, token in enumerate(prefix):
            tokens[i] = self.space.ids[token]+1
        weights = [0.] * self.p.max_factors
        for slot, (expr, weight) in enumerate(sorted(pool.items())):
            for j, token in enumerate(self.space.parse(expr).tokens):
                tokens[self.p.max_tokens*(slot+1)+j] = self.space.ids[token]+1
            weights[slot] = weight
        return dict(tokens=tokens, valid=[float(t != 0) for t in tokens], pool_weights=weights)

    def tensors(self, observations, masks):
        return (torch.tensor([o["tokens"] for o in observations], dtype=torch.long),
                torch.tensor([o["valid"] for o in observations], dtype=torch.float32),
                torch.tensor([o["pool_weights"] for o in observations], dtype=torch.float32),
                torch.tensor(masks, dtype=torch.bool))

    def collect(self, pool, batch_id):
        episodes = []
        policy_id = self.parameter_digest()
        for _ in range(self.p.episodes_per_batch):
            prefix, steps = [], []
            while True:
                mask = self.space.mask(prefix).tolist()
                observation = self.observation(prefix, pool)
                with torch.no_grad():
                    distribution, value = self.model(*self.tensors([observation], [mask]))
                    if self.p.generator == "random":
                        distribution = Categorical(logits=torch.zeros_like(distribution.logits).masked_fill(~torch.tensor([mask]), -1e9))
                    action = distribution.sample()
                    steps.append(dict(observation=observation, mask=mask, action=int(action.item()),
                                      old_log_probability=float(distribution.log_prob(action).item()), old_value=float(value.item())))
                if action.item() == 0:
                    break
                prefix.append(self.space.vocabulary[action.item()])
            episodes.append(dict(batch_id=batch_id, policy_id=policy_id, expression=self.space.from_prefix(prefix).text,
                                 sampled_prefix=prefix, steps=steps, reward=None))
        return episodes

    def update(self, episodes, batch_id):
        if not episodes or batch_id <= self.last_updated_batch:
            raise ValueError("empty or already updated rollout batch")
        policy_id = self.parameter_digest()
        if any(e["batch_id"] != batch_id or e["policy_id"] != policy_id or e["reward"] is None for e in episodes):
            raise ValueError("cross-batch / stale-policy / unevaluated trajectories are not on-policy")
        steps = [s for e in episodes for s in e["steps"]]
        args = self.tensors([s["observation"] for s in steps], [s["mask"] for s in steps])
        actions = torch.tensor([s["action"] for s in steps], dtype=torch.long)
        old_log = torch.tensor([s["old_log_probability"] for s in steps])
        old_values = torch.tensor([s["old_value"] for s in steps])
        returns = torch.tensor([e["reward"] for e in episodes for _ in e["steps"]], dtype=torch.float32)
        advantage = returns - old_values
        before = torch.cat([v.detach().flatten().clone() for v in self.model.parameters()])
        losses = []
        initial_ratio_error = 0.
        for epoch in range(self.p.ppo_epochs):
            distribution, values = self.model(*args)
            ratio = torch.exp(distribution.log_prob(actions)-old_log)
            if epoch == 0:
                initial_ratio_error = float((ratio.detach()-1).abs().max())
            surrogate = torch.minimum(ratio*advantage, ratio.clamp(1-self.p.clip_ratio, 1+self.p.clip_ratio)*advantage)
            policy_loss = -surrogate.mean()
            value_loss = (values-returns).square().mean()
            entropy = distribution.entropy().mean()
            loss = policy_loss + self.p.value_coefficient*value_loss-self.p.entropy_coefficient*entropy
            if not torch.isfinite(loss):
                raise RuntimeError("nonfinite PPO loss")
            self.optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(self.model.parameters(), 0.5, error_if_nonfinite=True)
            self.optimizer.step()
            losses.append(dict(epoch=epoch, loss=float(loss.detach()), policy_loss=float(policy_loss.detach()),
                               value_loss=float(value_loss.detach()), entropy=float(entropy.detach())))
        after = torch.cat([v.detach().flatten() for v in self.model.parameters()])
        self.last_updated_batch = batch_id
        return dict(batch_id=batch_id, before=policy_id, after=self.parameter_digest(),
                    parameter_l2_change=float(torch.linalg.vector_norm(after-before)),
                    initial_ratio_max_error=initial_ratio_error, episodes=len(episodes), steps=len(steps),
                    negative_episodes=sum(e["reward"] < 0 for e in episodes), gamma=1., losses=losses)

    def state(self):
        return dict(model=self.model.state_dict(), optimizer=self.optimizer.state_dict(),
                    torch_rng=torch.get_rng_state(), numpy_rng=np.random.get_state(), python_rng=random.getstate(),
                    last_updated_batch=self.last_updated_batch)

    def restore(self, state):
        self.model.load_state_dict(state["model"])
        self.optimizer.load_state_dict(state["optimizer"])
        torch.set_rng_state(state["torch_rng"])
        np.random.set_state(state["numpy_rng"])
        random.setstate(state["python_rng"])
        self.last_updated_batch = state["last_updated_batch"]
