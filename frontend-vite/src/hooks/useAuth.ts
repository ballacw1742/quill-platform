import { useState, useEffect } from 'react';
import { auth, onAuthStateChanged, handleRedirectResult, type User } from '../lib/firebase';

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let unsubscribe: () => void;

    // Process redirect result first, then set up listener
    handleRedirectResult()
      .then((result) => {
        if (result?.user) {
          setUser(result.user);
        }
      })
      .catch(console.error)
      .finally(() => {
        // Auth state listener handles the ongoing state
        unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
          setUser(firebaseUser);
          setLoading(false);
        });
      });

    return () => { if (unsubscribe) unsubscribe(); };
  }, []);

  return { user, loading };
}
