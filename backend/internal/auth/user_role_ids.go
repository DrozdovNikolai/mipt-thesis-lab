package auth

import (
	"math/big"

	"github.com/google/uuid"
)

// Missing-role messages expose iteration of set(UUIDs) - set(found UUIDs).
// UUID hashes are integer hashes; reproduce the frozen CPython 3.11 table
// traversal, including the copy/difference size heuristic, for these messages.
// Algorithm reference: https://github.com/python/cpython/blob/v3.11.14/Objects/setobject.c
type userUUIDSlot struct {
	id   uuid.UUID
	hash uint64
	used bool
}
type userUUIDSet struct {
	slots []userUUIDSlot
	used  int
}

func userUUIDHash(id uuid.UUID) uint64 {
	value := new(big.Int).SetBytes(id[:])
	return value.Mod(value, new(big.Int).SetUint64((1<<61)-1)).Uint64()
}

func (s *userUUIDSet) insert(slot userUUIDSlot) {
	mask := uint64(len(s.slots) - 1)
	index, perturb := slot.hash&mask, slot.hash
	for {
		last := index
		if index+9 <= mask {
			last += 9
		}
		for probe := index; probe <= last; probe++ {
			if !s.slots[probe].used {
				s.slots[probe] = slot
				return
			}
		}
		perturb >>= 5
		index = (index*5 + 1 + perturb) & mask
	}
}

func (s *userUUIDSet) resize(minimum int) {
	old, size := s.slots, 8
	for size <= minimum {
		size *= 2
	}
	s.slots = make([]userUUIDSlot, size)
	for _, slot := range old {
		if slot.used {
			s.insert(slot)
		}
	}
}

func (s *userUUIDSet) addDistinct(slot userUUIDSlot) {
	s.insert(slot)
	s.used++
	if s.used*5 >= (len(s.slots)-1)*3 {
		factor := 4
		if s.used > 50000 {
			factor = 2
		}
		s.resize(s.used * factor)
	}
}

func userMissingRoleIDs(ids []uuid.UUID, found map[uuid.UUID]bool) []string {
	source := userUUIDSet{slots: make([]userUUIDSlot, 8)}
	seen := map[uuid.UUID]bool{}
	for _, id := range ids {
		if !seen[id] {
			seen[id] = true
			source.addDistinct(userUUIDSlot{id: id, hash: userUUIDHash(id), used: true})
		}
	}
	result := userUUIDSet{slots: make([]userUUIDSlot, 8)}
	if source.used>>2 > len(found) {
		if source.used*5 >= 7*3 {
			result.resize(source.used * 2)
		}
		if len(result.slots) == len(source.slots) {
			copy(result.slots, source.slots)
		} else {
			for _, slot := range source.slots {
				if slot.used {
					result.insert(slot)
				}
			}
		}
		result.used = source.used
		for i, slot := range result.slots {
			if slot.used && found[slot.id] {
				result.slots[i].used = false
				result.used--
			}
		}
		if source.used-result.used > (len(result.slots)-1)/4 {
			factor := 4
			if result.used > 50000 {
				factor = 2
			}
			result.resize(result.used * factor)
		}
	} else {
		for _, slot := range source.slots {
			if slot.used && !found[slot.id] {
				result.addDistinct(slot)
			}
		}
	}
	missing := []string{}
	for _, slot := range result.slots {
		if slot.used {
			missing = append(missing, slot.id.String())
		}
	}
	return missing
}
