import { useState, useEffect } from "react";
import { auth, onAuthStateChanged, handleRedirectResult, type User } from "../lib/firebase";

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // First handle any pending redirect result from Google sign-in
    handleRedirectResult()
      .then((result) => {
        if (result?.user) {
          setUser(result.user);
          setLoading(false);
        }
      })
      .catch(console.error)
      .finally(() => {
        // Then set up the auth state listener
        const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
          setUser(firebaseUser);
          setLoading(false);
        });
        // Note: cleanup not perfect here but works for SPA
        return () => unsubscribe();
      });
  }, []);

  return { user, loading };
}
