// Connection settings: the whole site signs in to the same private Supabase
// database as the F&O Desk and reads its data from there.
// The publishable key is designed to be public; your trades stay private through
// the access rules in fno-desk/supabase/003_cash_trades.sql, which only let the
// email below in.
window.SS_CONFIG = {
  supabaseUrl: "https://ggybblynosipnqbzedsx.supabase.co",
  supabaseAnonKey: "sb_publishable_5_59_LRgNx4q3QjFE73cLw_7ixcvAk1",
  email: "vs916491@gmail.com",
};
