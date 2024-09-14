## Introduction



## Node



### run



## start


raft.newRaft


```go
func newRaft(c *Config) *raft {
   if err := c.validate(); err != nil {
      panic(err.Error())
   }
   raftlog := newLogWithSize(c.Storage, c.Logger, c.MaxCommittedSizePerReady)
   hs, cs, err := c.Storage.InitialState()
   if err != nil {
      panic(err) // TODO(bdarnell)
   }

   r := &raft{
      id:                        c.ID,
      lead:                      None,
      isLearner:                 false,
      raftLog:                   raftlog,
      maxMsgSize:                c.MaxSizePerMsg,
      maxUncommittedSize:        c.MaxUncommittedEntriesSize,
      prs:                       tracker.MakeProgressTracker(c.MaxInflightMsgs),
      electionTimeout:           c.ElectionTick,
      heartbeatTimeout:          c.HeartbeatTick,
      logger:                    c.Logger,
      checkQuorum:               c.CheckQuorum,
      preVote:                   c.PreVote,
      readOnly:                  newReadOnly(c.ReadOnlyOption),
      disableProposalForwarding: c.DisableProposalForwarding,
   }

   cfg, prs, err := confchange.Restore(confchange.Changer{
      Tracker:   r.prs,
      LastIndex: raftlog.lastIndex(),
   }, cs)
   if err != nil {
      panic(err)
   }
   assertConfStatesEquivalent(r.logger, cs, r.switchToConfig(cfg, prs))

   if !IsEmptyHardState(hs) {
      r.loadState(hs)
   }
   if c.Applied > 0 {
      raftlog.appliedTo(c.Applied)
   }
   r.becomeFollower(r.Term, None)

   var nodesStrs []string
   for _, n := range r.prs.VoterNodes() {
      nodesStrs = append(nodesStrs, fmt.Sprintf("%x", n))
   }

   r.logger.Infof("newRaft %x [peers: [%s], term: %d, commit: %d, applied: %d, lastindex: %d, lastterm: %d]",
      r.id, strings.Join(nodesStrs, ","), r.Term, r.raftLog.committed, r.raftLog.applied, r.raftLog.lastIndex(), r.raftLog.lastTerm())
   return r
}
```





### folllower

```go
func (r *raft) becomeFollower(term uint64, lead uint64) {
   r.step = stepFollower
   r.reset(term)
   r.tick = r.tickElection
   r.lead = lead
   r.state = StateFollower
   r.logger.Infof("%x became follower at term %d", r.id, r.Term)
}
```





```go
func (r *raft) tickElection() {
   r.electionElapsed++

   if r.promotable() && r.pastElectionTimeout() {
      r.electionElapsed = 0
      r.Step(pb.Message{From: r.id, Type: pb.MsgHup})
   }
}
```



如果Cluster开启PreVote模式 当Follower选举计时器timout后会调用becomePreCandidate切换state到PreCandidate



```go
func (r *raft) becomePreCandidate() {
   // TODO(xiangli) remove the panic when the raft implementation is stable
   if r.state == StateLeader {
      panic("invalid transition [leader -> pre-candidate]")
   }
   // Becoming a pre-candidate changes our step functions and state,
   // but doesn't change anything else. In particular it does not increase
   // r.Term or change r.Vote.
   r.step = stepCandidate
   r.prs.ResetVotes()
   r.tick = r.tickElection
   r.lead = None
   r.state = StatePreCandidate
   r.logger.Infof("%x became pre-candidate at term %d", r.id, r.Term)
}
```

当节点可联系到半数以上节点后 调用

```go
func (r *raft) becomeCandidate() {
   // TODO(xiangli) remove the panic when the raft implementation is stable
   if r.state == StateLeader {
      panic("invalid transition [leader -> candidate]")
   }
   r.step = stepCandidate
   r.reset(r.Term + 1)
   r.tick = r.tickElection
   r.Vote = r.id
   r.state = StateCandidate
   r.logger.Infof("%x became candidate at term %d", r.id, r.Term)
}
```



获取quorum后

```go
func (r *raft) becomeLeader() {
   // TODO(xiangli) remove the panic when the raft implementation is stable
   if r.state == StateFollower {
      panic("invalid transition [follower -> leader]")
   }
   r.step = stepLeader
   r.reset(r.Term)
   r.tick = r.tickHeartbeat
   r.lead = r.id
   r.state = StateLeader
   // Followers enter replicate mode when they've been successfully probed
   // (perhaps after having received a snapshot as a result). The leader is
   // trivially in this state. Note that r.reset() has initialized this
   // progress with the last index already.
   r.prs.Progress[r.id].BecomeReplicate()

   // Conservatively set the pendingConfIndex to the last index in the
   // log. There may or may not be a pending config change, but it's
   // safe to delay any future proposals until we commit all our
   // pending log entries, and scanning the entire tail of the log
   // could be expensive.
   r.pendingConfIndex = r.raftLog.lastIndex()

   emptyEnt := pb.Entry{Data: nil}
   if !r.appendEntry(emptyEnt) {
      // This won't happen because we just called reset() above.
      r.logger.Panic("empty entry was dropped")
   }
   // As a special case, don't count the initial empty entry towards the
   // uncommitted log quota. This is because we want to preserve the
   // behavior of allowing one entry larger than quota if the current
   // usage is zero.
   r.reduceUncommittedSize([]pb.Entry{emptyEnt})
   r.logger.Infof("%x became leader at term %d", r.id, r.Term)
}
```



appendEntry

```go
func (r *raft) appendEntry(es ...pb.Entry) (accepted bool) {
   li := r.raftLog.lastIndex()
   for i := range es {
      es[i].Term = r.Term
      es[i].Index = li + 1 + uint64(i)
   }
   // Track the size of this uncommitted proposal.
   if !r.increaseUncommittedSize(es) {
      r.logger.Debugf(
         "%x appending new entries to log would exceed uncommitted entry size limit; dropping proposal",
         r.id,
      )
      // Drop the proposal.
      return false
   }
   // use latest "last" index after truncate/append
   li = r.raftLog.append(es...)
   r.prs.Progress[r.id].MaybeUpdate(li)
   // Regardless of maybeCommit's return, our caller will call bcastAppend.
   r.maybeCommit()
   return true
}
```





```go
func (pr *Progress) MaybeUpdate(n uint64) bool {
   var updated bool
   if pr.Match < n {
      pr.Match = n
      updated = true
      pr.ProbeAcked()
   }
   pr.Next = max(pr.Next, n+1)
   return updated
}
```



commit

```go
func (r *raft) maybeCommit() bool {
   mci := r.prs.Committed()
   return r.raftLog.maybeCommit(mci, r.Term)
}
```







## Log



### newLog

初始化storage字段

```go
func newLog(storage Storage, logger Logger) *raftLog {
   return newLogWithSize(storage, logger, noLimit)
}

// newLogWithSize returns a log using the given storage and max message size.
func newLogWithSize(storage Storage, logger Logger, maxNextEntsSize uint64) *raftLog {
   if storage == nil {
      log.Panic("storage must not be nil")
   }
   log := &raftLog{
      storage:         storage,
      logger:          logger,
      maxNextEntsSize: maxNextEntsSize,
   }
   firstIndex, err := storage.FirstIndex()
   if err != nil {
      panic(err) // TODO(bdarnell)
   }
   lastIndex, err := storage.LastIndex()
   if err != nil {
      panic(err) // TODO(bdarnell)
   }
   log.unstable.offset = lastIndex + 1
   log.unstable.logger = logger
   // Initialize our committed and applied pointers to the time of the last compaction.
   log.committed = firstIndex - 1
   log.applied = firstIndex - 1

   return log
}
```



### append

```go
func (l *raftLog) maybeAppend(index, logTerm, committed uint64, ents ...pb.Entry) (lastnewi uint64, ok bool) {
   if l.matchTerm(index, logTerm) {
      lastnewi = index + uint64(len(ents))
      ci := l.findConflict(ents)
      switch {
      case ci == 0:
      case ci <= l.committed:
         l.logger.Panicf("entry %d conflict with committed entry [committed(%d)]", ci, l.committed)
      default:
         offset := index + 1
         l.append(ents[ci-offset:]...)
      }
      l.commitTo(min(committed, lastnewi))
      return lastnewi, true
   }
   return 0, false
}
```



#### matchTerm

```go
func (l *raftLog) matchTerm(i, term uint64) bool {
   t, err := l.term(i)
   if err != nil {
      return false
   }
   return t == term
}
```

先去unstable查询 否则去storage里查询

```go
func (l *raftLog) term(i uint64) (uint64, error) {
   // the valid term range is [index of dummy entry, last index]
   dummyIndex := l.firstIndex() - 1
   if i < dummyIndex || i > l.lastIndex() {
      // TODO: return an error instead?
      return 0, nil
   }

   if t, ok := l.unstable.maybeTerm(i); ok {
      return t, nil
   }

   t, err := l.storage.Term(i)
   if err == nil {
      return t, nil
   }
   if err == ErrCompacted || err == ErrUnavailable {
      return 0, err
   }
   panic(err) // TODO(bdarnell)
}
```



#### findConflict

```go
func (l *raftLog) findConflict(ents []pb.Entry) uint64 {
   for _, ne := range ents {
      if !l.matchTerm(ne.Index, ne.Term) {
         if ne.Index <= l.lastIndex() {
            l.logger.Infof("found conflict at index %d [existing term: %d, conflicting term: %d]",
               ne.Index, l.zeroTermOnErrCompacted(l.term(ne.Index)), ne.Term)
         }
         return ne.Index
      }
   }
   return 0
}
```





















## Links

- [etcd]()
